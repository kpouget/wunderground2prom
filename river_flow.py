#!/usr/bin/env python3
import os
import socket
import time
import logging
import argparse
import datetime
import json
import urllib

from prometheus_client import start_http_server, Gauge, CollectorRegistry

logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("river_flow_exporter.log"),
              logging.StreamHandler()],
    datefmt='%Y-%m-%d %H:%M:%S')

logging.info("""river_flow.py - Expose river flow readings in Prometheus format

Press Ctrl+C to exit!

""")

DEBUG = os.getenv('DEBUG', 'false') == 'true'

# Create custom registry to disable default Python process metrics
CUSTOM_REGISTRY = CollectorRegistry()

# River metrics
_RIVERS_FLOW = Gauge('river_flow', 'Flow of the river (m3/s)', ["river", "station", "station_id"], registry=CUSTOM_REGISTRY)
_RIVERS_HEIGHT = Gauge('river_height', 'Height of the river (m)', ["river", "station", "station_id"], registry=CUSTOM_REGISTRY)

# Health monitoring metrics
_RIVER_LAST_FETCH_TIME = Gauge('river_last_fetch_time', 'Unix timestamp of last successful river data fetch', ["river", "station", "station_id"], registry=CUSTOM_REGISTRY)
_RIVER_LAST_FETCH_DURATION = Gauge('river_last_fetch_duration', 'Duration of last successful river API request (seconds)', ["river", "station", "station_id"], registry=CUSTOM_REGISTRY)
_RIVER_SUCCESSFUL_REQUESTS_TOTAL = Gauge('river_successful_requests_total', 'Total number of successful river API requests', ["river", "station", "station_id"], registry=CUSTOM_REGISTRY)
_RIVER_DATA_LAST_CHANGE = Gauge('river_data_last_change', 'Unix timestamp when river data last changed', ["river", "station", "station_id"], registry=CUSTOM_REGISTRY)

# River monitoring stations configuration
RIVER_STATIONS = [
    {
        "river": "Lot",
        "station": "Cahors",
        "station_id": "O823153002",
        "description": "Lot river at Cahors"
    },
    {
        "river": "Dordogne",
        "station": "Carennac",
        "station_id": "P207002001",
        "description": "Dordogne river at Carennac"
    },
    {
        "river": "Dordogne",
        "station": "Souillac",
        "station_id": "P230001001",
        "description": "Dordogne river at Souillac"
    }
]

# Health tracking variables
previous_river_data = {}  # station_key -> {'flow': value, 'height': value}
successful_river_requests = {}  # station_key -> count


def str_to_bool(value):
    if value.lower() in {'false', 'f', '0', 'no', 'n'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y'}:
        return True
    raise ValueError('{} is not a valid boolean value'.format(value))


def get_level(river_code, serie):
    """Get river flow level from Vigicrues API"""
    URL = "https://www.vigicrues.gouv.fr/services/observations.json/index.php?CdStationHydro={}&GrdSerie={}&FormatSortie=simple"

    url = URL.format(river_code, serie)
    start_time = time.time()
    try:
        # Add 30-second timeout to prevent hanging
        content = urllib.request.urlopen(url, timeout=30).read().decode('utf-8')
        measures = json.loads(content)

        # Debug: Examine the raw data structure
        if DEBUG:
            logging.debug(f"Raw API response for {river_code}/{serie}:")
            logging.debug(f"Serie keys: {list(measures.get('Serie', {}).keys())}")

            obs_data = measures.get("Serie", {}).get("ObssHydro", [])
            logging.debug(f"Total data points: {len(obs_data)}")

            # Show last 5 data points to understand the pattern
            recent_points = obs_data[-5:] if len(obs_data) >= 5 else obs_data
            logging.debug(f"Recent data points for {river_code}/{serie}:")
            for i, point in enumerate(recent_points, start=max(0, len(obs_data)-5)):
                timestamp = point[0] if len(point) > 0 else "N/A"
                value = point[1] if len(point) > 1 else "N/A"
                logging.debug(f"  [{i}] timestamp: {timestamp}, value: {value} (type: {type(value)})")

        # Extract the measurement value
        obs_hydro = measures["Serie"]["ObssHydro"]
        if not obs_hydro:
            logging.warning(f"No observation data for {river_code}/{serie}")
            return None, None

        # Get the most recent data point
        latest_point = obs_hydro[-1]
        hauteur = latest_point[1]

        # Additional validation and debug info
        if hauteur is None:
            logging.warning(f"Latest data point for {river_code}/{serie} has null value")
            # Try the second-to-last point if available
            if len(obs_hydro) > 1:
                hauteur = obs_hydro[-2][1]
                logging.debug(f"Using second-to-last value: {hauteur}")

        # Log precision and value details
        if hauteur is not None:
            logging.debug(f"Extracted value for {river_code}/{serie}: {hauteur} (type: {type(hauteur)}, precision: {hauteur if isinstance(hauteur, (int, float)) else 'N/A'})")

            # Check if value looks rounded (ends in .0, .5, etc.)
            if isinstance(hauteur, (int, float)) and hauteur != 0:
                decimal_part = hauteur - int(hauteur)
                if decimal_part == 0.0:
                    logging.debug(f"Value {hauteur} appears to be rounded to integer")
                elif abs(decimal_part - 0.5) < 0.001:
                    logging.debug(f"Value {hauteur} appears to be rounded to 0.5")

        elapsed = time.time() - start_time
        logging.debug(f"River API request for {river_code}/{serie} completed in {elapsed:.2f}s, value: {hauteur}")

        # Return both value and duration for successful requests
        return hauteur, elapsed
    except socket.timeout:
        elapsed = time.time() - start_time
        logging.warning(f"River API timeout for {river_code}/{serie} after {elapsed:.2f}s")
        return None, None
    except urllib.error.URLError as e:
        elapsed = time.time() - start_time
        logging.error(f"Network error for river {river_code}/{serie} after {elapsed:.2f}s: {e}")
        return None, None
    except Exception as e:
        elapsed = time.time() - start_time
        logging.error(f"Unexpected error for river {river_code}/{serie} after {elapsed:.2f}s: {e}")
        return None, None


def update_river_data(station_config):
    """Update flow and height data for a specific river station"""
    current_time = time.time()
    river = station_config["river"]
    station = station_config["station"]
    station_id = station_config["station_id"]

    # Create unique key for tracking this station
    station_key = f"{river}_{station}_{station_id}"

    # Get labeled metrics for this station
    flow_gauge = _RIVERS_FLOW.labels(river=river, station=station, station_id=station_id)
    height_gauge = _RIVERS_HEIGHT.labels(river=river, station=station, station_id=station_id)

    # Get health monitoring metrics for this station
    last_fetch_time = _RIVER_LAST_FETCH_TIME.labels(river=river, station=station, station_id=station_id)
    last_fetch_duration = _RIVER_LAST_FETCH_DURATION.labels(river=river, station=station, station_id=station_id)
    successful_requests_total = _RIVER_SUCCESSFUL_REQUESTS_TOTAL.labels(river=river, station=station, station_id=station_id)
    data_last_change = _RIVER_DATA_LAST_CHANGE.labels(river=river, station=station, station_id=station_id)

    # Track successful request count
    total_requests = 0
    successful_durations = []

    # Get flow data
    flow_value, flow_duration = get_level(station_id, "Q")
    if flow_value is not None:
        flow_gauge.set(flow_value)
        logging.info(f"{river} {station} flow: {flow_value} m3/s")
        total_requests += 1
        successful_durations.append(flow_duration)
    else:
        logging.warning(f"Failed to get {river} {station} flow data")

    # Get height data
    height_value, height_duration = get_level(station_id, "H")
    if height_value is not None:
        height_gauge.set(height_value)
        logging.info(f"{river} {station} height: {height_value} m")
        total_requests += 1
        successful_durations.append(height_duration)
    else:
        logging.warning(f"Failed to get {river} {station} height data")

    # Update health metrics if we had any successful requests
    if total_requests > 0:
        # Update last fetch time and duration
        last_fetch_time.set(current_time)
        avg_duration = sum(successful_durations) / len(successful_durations)
        last_fetch_duration.set(avg_duration)

        # Update successful request count
        successful_river_requests[station_key] = successful_river_requests.get(station_key, 0) + total_requests
        successful_requests_total.set(successful_river_requests[station_key])

        # Check for data changes
        current_data = {'flow': flow_value, 'height': height_value}
        previous_data = previous_river_data.get(station_key, {})

        # Check if any value changed
        data_changed = False
        for key, value in current_data.items():
            if value is not None and previous_data.get(key) != value:
                data_changed = True
                logging.debug(f"{river} {station} {key} changed: {previous_data.get(key)} -> {value}")

        if data_changed:
            data_last_change.set(current_time)
            previous_river_data[station_key] = current_data


def generate_hauteurs():
    """Update river flow and height metrics for all stations"""
    for station in RIVER_STATIONS:
        update_river_data(station)


def collect_all_data():
    """Collects all the river data currently set"""
    sensor_data = {}

    # Collect flow data
    flow_samples = _RIVERS_FLOW.collect()[0].samples
    for sample in flow_samples:
        river = sample.labels.get('river', 'unknown')
        station = sample.labels.get('station', 'unknown')
        station_id = sample.labels.get('station_id', 'unknown')
        sensor_data[f"river_flow_{river}_{station}"] = sample.value

    # Collect height data
    height_samples = _RIVERS_HEIGHT.collect()[0].samples
    for sample in height_samples:
        river = sample.labels.get('river', 'unknown')
        station = sample.labels.get('station', 'unknown')
        station_id = sample.labels.get('station_id', 'unknown')
        sensor_data[f"river_height_{river}_{station}"] = sample.value

    # Collect health metrics
    health_metrics = [_RIVER_LAST_FETCH_TIME, _RIVER_LAST_FETCH_DURATION,
                      _RIVER_SUCCESSFUL_REQUESTS_TOTAL, _RIVER_DATA_LAST_CHANGE]

    for metric in health_metrics:
        samples = metric.collect()[0].samples
        for sample in samples:
            river = sample.labels.get('river', 'unknown')
            station = sample.labels.get('station', 'unknown')
            station_id = sample.labels.get('station_id', 'unknown')
            metric_name = sample.name
            sensor_data[f"{metric_name}_{river}_{station}"] = sample.value

    return sensor_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--bind", metavar='ADDRESS', default='0.0.0.0', help="Specify alternate bind address [default: 0.0.0.0]")
    parser.add_argument("-p", "--port", metavar='PORT', default=8001, type=int, help="Specify alternate port [default: 8001]")
    parser.add_argument("-d", "--debug", metavar='DEBUG', type=str_to_bool, help="Turns on more verbose logging [default: false]")
    parser.add_argument("-i", "--interval", metavar='SECONDS', default=300, type=int, help="Update interval in seconds [default: 300]")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    first = True
    logging.info(f"Starting river flow monitoring (update interval: {args.interval}s)")

    while True:
        # Update river flow data
        try:
            generate_hauteurs()
        except Exception as e:
            logging.exception("Failed to generate the river flow and height data ...")

        if first:
            # Start up the server to expose the metrics.
            start_http_server(addr=args.bind, port=args.port, registry=CUSTOM_REGISTRY)
            logging.info("Listening on http://{}:{}".format(args.bind, args.port))
            stations_info = ", ".join([f"{s['river']} at {s['station']} ({s['station_id']})" for s in RIVER_STATIONS])
            logging.info(f"Monitoring {len(RIVER_STATIONS)} river stations - Flow & Height: {stations_info}")
            first = False

        if DEBUG:
            logging.info('River data: {}'.format(collect_all_data()))

        time.sleep(args.interval)