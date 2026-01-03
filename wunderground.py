#!/usr/bin/env python3
import os
import random
import requests
import socket
import time
import logging
import argparse
import subprocess
import datetime

from threading import Thread

import json
import urllib
import yaml

from prometheus_client import start_http_server, Gauge, Histogram, CollectorRegistry

logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("wunderground2prom.log"),
              logging.StreamHandler()],
    datefmt='%Y-%m-%d %H:%M:%S')

logging.info("""my_exporter.py - Expose readings from the what I'm interested in in Prometheus format

Press Ctrl+C to exit!

""")

DEBUG = os.getenv('DEBUG', 'false') == 'true'

# ---

PRESSURE_OFFSET = 0

# ---

# Create custom registry to disable default Python process metrics
CUSTOM_REGISTRY = CollectorRegistry()

# ---

GAUGES = {
    'humidity': ("Humidity (in %)", ["station_id"]),
    'rain': ('Rain (in mm)', ["mode", "station_id"]),

    'wind': ('Wind speed (in km/h)', ["mode", "station_id"]),
    'wind_dir': ('Wind direction (in *)', ["station_id"]),

    'uv_idx': ('UV index', ["station_id"]),
    'sun_rad': ('Sun radiation', ["station_id"]),

    'pressure': ("Pression (in hPa)", ["station_id"]),
    'temperature': ("Temperature", ["mode", "station_id"]),

    # Health monitoring metrics
    'last_fetch_time': ("Unix timestamp of last successful data fetch", ["station_id"]),
    'last_fetch_duration': ("Duration of last successful API request (seconds)", ["station_id"]),
    'successful_requests_total': ("Total number of successful API requests", ["station_id"]),
    'temperature_last_change': ("Unix timestamp when temperature last changed", ["station_id"]),
    'station_data_age': ("Age of station data in seconds (how old the station's last update is)", ["station_id"]),
}

PROPS = {
    "temp": ('temperature', dict(mode="actual")),
    "dewpt": ('temperature',  dict(mode="dew_point")),
    "heatIndex": ('temperature',  dict(mode="heat_index")),
    "windChill": ('temperature',  dict(mode="wind_chill")),

    "humidity": ('humidity', {}),

    "precipRate": ('rain', dict(mode="rate")),
    "precipTotal": ('rain', dict(mode="total")),

    "windSpeed": ('wind', dict(mode="speed")),
    "windGust": ('wind', dict(mode="gust")),
    "winddir": ('wind_dir', {}),

    "uv": ('uv_idx', {}),
    "solarRadiation": ('sun_rad', {}),

    "pressure": ('pressure', {}),
    "station_data_age": ('station_data_age', {}),
}

def prepare_gauges(gauges_def):
    gauges = {}
    for metric, props in gauges_def.items():
        if isinstance(props, str):
            descr = props
            labels = []
        else:
            descr, labels = props

        gauges[metric] = Gauge(metric, descr, labels, registry=CUSTOM_REGISTRY)

    return gauges

def create_labeled_metrics(gauges, props_def, station_id):
    labeled_gauges = {}
    for key, props in props_def.items():
        metric, labels = props

        gauge = gauges[metric]

        # Add station_id to all labels
        labels_with_station = labels.copy()
        labels_with_station['station_id'] = station_id

        labeled_gauge = gauge.labels(**labels_with_station)
        labeled_gauges[key] = labeled_gauge

    return labeled_gauges

GAUGES_REGISTRY = prepare_gauges(GAUGES)

# Health monitoring tracking
previous_temperatures = {}  # station_id -> temperature value
successful_request_counts = {}  # station_id -> count

# ---

def get_data(station_id, api_key):
    url = f"https://api.weather.com/v2/pws/observations/current?apiKey={api_key}&stationId={station_id}&numericPrecision=decimal&format=json&units=m"

    start_time = time.time()
    try:
        req = urllib.request.Request(url,  headers={'User-Agent': 'Mozilla/5.0'})
        # Add 30-second timeout to prevent hanging
        response = urllib.request.urlopen(req, timeout=30).read()

        elapsed = time.time() - start_time
        logging.debug(f"API request for {station_id} completed in {elapsed:.2f}s")

        data = json.loads(response)
        data = data["observations"][0]

        # Extract station update timestamp before processing metric data
        station_update_time = None
        for timestamp_field in ["obsTimeUtc", "epoch", "obsTimeLocal", "timestamp"]:
            if timestamp_field in data:
                try:
                    if timestamp_field == "obsTimeUtc":
                        # Parse ISO format: "2024-01-01T10:15:00Z"
                        station_update_time = datetime.datetime.fromisoformat(data[timestamp_field].replace('Z', '+00:00')).timestamp()
                    elif timestamp_field == "epoch":
                        # Direct Unix timestamp
                        station_update_time = float(data[timestamp_field])
                    elif timestamp_field == "obsTimeLocal":
                        # Parse local time format, assume it's close enough for age calculation
                        station_update_time = datetime.datetime.fromisoformat(data[timestamp_field]).timestamp()
                    else:
                        # Try parsing as Unix timestamp or ISO format
                        if isinstance(data[timestamp_field], (int, float)):
                            station_update_time = float(data[timestamp_field])
                        else:
                            station_update_time = datetime.datetime.fromisoformat(data[timestamp_field]).timestamp()

                    logging.debug(f"Station {station_id} data timestamp ({timestamp_field}): {data[timestamp_field]} -> {station_update_time}")
                    break
                except (ValueError, TypeError) as e:
                    logging.debug(f"Failed to parse {timestamp_field} for station {station_id}: {e}")
                    continue

        # Add station data age to the data
        if station_update_time:
            current_time = time.time()
            station_data_age = current_time - station_update_time
            data["station_data_age"] = station_data_age
            logging.debug(f"Station {station_id} data is {station_data_age:.1f} seconds old")
        else:
            logging.warning(f"No valid timestamp found in station {station_id} data")
            logging.debug(f"Available keys: {list(data.keys())}")

        mtr = data.pop("metric")
        data.update(mtr)
        # Return both data and duration for successful requests
        return data, elapsed
    except socket.timeout:
        elapsed = time.time() - start_time
        logging.warning(f"API request timeout for station {station_id} after {elapsed:.2f}s")
        return None, None
    except urllib.error.URLError as e:
        elapsed = time.time() - start_time
        logging.error(f"Network error for station {station_id} after {elapsed:.2f}s: {e}")
        return None, None
    except Exception as e:
        elapsed = time.time() - start_time
        logging.error(f"Unexpected error for station {station_id} after {elapsed:.2f}s: {e}")
        return None, None

def get_wunderground(station):
    station_id = station["id"]
    station_name = station["name"]
    api_key = station["api_key"]

    data, fetch_duration = get_data(station_id, api_key)
    has_errors = []

    if not data:
        logging.warning(f"No data available for station {station_name} ({station_id}) at {datetime.datetime.now()}")
        return

    current_time = time.time()

    # Create labeled metrics for this station (weather data)
    metrics = create_labeled_metrics(GAUGES_REGISTRY, PROPS, station_id)

    # Create health monitoring metrics for this station
    health_metrics = {}
    health_metrics['last_fetch_time'] = GAUGES_REGISTRY['last_fetch_time'].labels(station_id=station_id)
    health_metrics['last_fetch_duration'] = GAUGES_REGISTRY['last_fetch_duration'].labels(station_id=station_id)
    health_metrics['successful_requests_total'] = GAUGES_REGISTRY['successful_requests_total'].labels(station_id=station_id)
    health_metrics['temperature_last_change'] = GAUGES_REGISTRY['temperature_last_change'].labels(station_id=station_id)
    health_metrics['station_data_age'] = GAUGES_REGISTRY['station_data_age'].labels(station_id=station_id)

    # Update health metrics for successful fetch
    health_metrics['last_fetch_time'].set(current_time)
    health_metrics['last_fetch_duration'].set(fetch_duration)

    # Increment successful request count
    successful_request_counts[station_id] = successful_request_counts.get(station_id, 0) + 1
    health_metrics['successful_requests_total'].set(successful_request_counts[station_id])

    # Process weather data
    current_temp = None
    for key, gauge in metrics.items():
        try:
            value = data[key]
        except KeyError:
            has_errors.append(key)
            continue
        if value is None:
            continue
        if key == "pressure":
            value -= PRESSURE_OFFSET

        # Track temperature for change detection (prefer "temp" but fallback to others)
        if key == "temp":
            current_temp = value
        elif current_temp is None and key in ["dewpt", "heatIndex", "windChill"]:
            current_temp = value
            logging.debug(f"Using {key} for temperature change detection: {value}")

        try:
            gauge.set(value)
        except:
            import pdb;pdb.set_trace()
            pass

    # Update temperature change tracking
    if current_temp is not None:
        previous_temp = previous_temperatures.get(station_id)

        # Handle floating point precision and first reading
        if previous_temp is None:
            # First reading - always set but don't consider it a "change"
            health_metrics['temperature_last_change'].set(current_time)
            previous_temperatures[station_id] = current_temp
            logging.debug(f"First temperature reading for {station_id}: {current_temp}")
        else:
            # Use small tolerance for floating point comparison
            temp_diff = abs(previous_temp - current_temp)
            if temp_diff >= 0.05:  # 0.05°C tolerance
                health_metrics['temperature_last_change'].set(current_time)
                previous_temperatures[station_id] = current_temp
                logging.debug(f"Temperature changed for {station_id}: {previous_temp} -> {current_temp} (diff: {temp_diff:.2f})")
            else:
                logging.debug(f"Temperature stable for {station_id}: {current_temp} (diff: {temp_diff:.3f})")
    else:
        logging.warning(f"No temperature data available for change detection for {station_id}")
        logging.debug(f"Available data keys: {list(data.keys())}")

    if has_errors:
        logging.info(f"Station {station_name} ({station_id}) - Missing keys: {', '.join(has_errors)}")
        logging.info(f"Station {station_name} ({station_id}) - Available keys: {', '.join(data.keys())}")

# ---
# ---

def collect_all_data():
    """Collects all the data currently set"""
    sensor_data = {}

    for key, gauge in GAUGES_REGISTRY.items():
        samples = gauge.collect()[0].samples
        if not samples:
            continue
        # Collect all samples (multiple stations will have multiple samples)
        for sample in samples:
            labels_key = f"{key}_{sample.labels.get('station_id', 'unknown')}"
            sensor_data[labels_key] = sample.value

    return sensor_data


def str_to_bool(value):
    if value.lower() in {'false', 'f', '0', 'no', 'n'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y'}:
        return True
    raise ValueError('{} is not a valid boolean value'.format(value))




if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--bind", metavar='ADDRESS', default='0.0.0.0', help="Specify alternate bind address [default: 0.0.0.0]")
    parser.add_argument("-p", "--port", metavar='PORT', default=8000, type=int, help="Specify alternate port [default: 8000]")
    parser.add_argument("-d", "--debug", metavar='DEBUG', type=str_to_bool, help="Turns on more verbose logging, showing sensor output and post responses [default: false]")
    args = parser.parse_args()

    if args.debug:
        DEBUG = True

    # Load configuration
    config_file = "stations.yaml"
    with open(config_file) as f:
        config = yaml.safe_load(f)
        api_key = config["api_key"]
        stations = config["stations"]

    # Add api_key to each station for convenience
    for station in stations:
        station["api_key"] = api_key

    # Store initial config file content for monitoring changes
    import hashlib
    with open(config_file, 'rb') as f:
        initial_config_hash = hashlib.md5(f.read()).hexdigest()

    first = True
    while True:
        # Check if configuration file has changed
        try:
            with open(config_file, 'rb') as f:
                current_config_hash = hashlib.md5(f.read()).hexdigest()
            if current_config_hash != initial_config_hash:
                logging.info(f"Configuration file {config_file} has changed. Exiting for restart.")
                exit(0)
        except Exception as e:
            logging.warning(f"Could not check config file: {e}")

        # Process each weather station
        for station in stations:
            try:
                get_wunderground(station)
            except Exception as e:
                logging.exception(f"Failed to generate the wunderground data for station {station['name']} ({station['id']}) ...")

        if first:
            # Start up the server to expose the metrics.
            start_http_server(addr=args.bind, port=args.port, registry=CUSTOM_REGISTRY)
            logging.info("Listening on http://{}:{}".format(args.bind, args.port))
            logging.info(f"Monitoring {len(stations)} weather stations: {', '.join([s['name'] for s in stations])}")
            first = False

        if DEBUG:
            logging.info('Sensor data: {}'.format(collect_all_data()))

        time.sleep(60)
