#!/usr/bin/env python3
import os
import random
import requests
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
    handlers=[logging.FileHandler("enviroplus_exporter.log"),
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

# ---

def get_data(station_id, api_key):
    url = f"https://api.weather.com/v2/pws/observations/current?apiKey={api_key}&stationId={station_id}&numericPrecision=decimal&format=json&units=m"

    try:
        req = urllib.request.Request(url,  headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req).read()

        data = json.loads(response)
        data = data["observations"][0]
        mtr = data.pop("metric")
        data.update(mtr)
        return data
    except Exception as e:
        logging.error(e)
        return None

def get_wunderground(station):
    station_id = station["id"]
    station_name = station["name"]
    api_key = station["api_key"]

    data = get_data(station_id, api_key)
    has_errors = []
    if not data:
        logging.warning(f"No data available for station {station_name} ({station_id}) at {datetime.datetime.now()}")
        return

    # Create labeled metrics for this station
    metrics = create_labeled_metrics(GAUGES_REGISTRY, PROPS, station_id)

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
        try:
            gauge.set(value)
        except:
            import pdb;pdb.set_trace()
            pass
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
