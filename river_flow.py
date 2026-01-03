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
_RIVERS_FLOW = Gauge('river_flow', 'Flow of the river (m3/s)', ["name"], registry=CUSTOM_REGISTRY)
_RIVERS_HEIGHT = Gauge('river_height', 'Height of the river (m)', ["name"], registry=CUSTOM_REGISTRY)

# Health monitoring metrics
_RIVER_LAST_FETCH_TIME = Gauge('river_last_fetch_time', 'Unix timestamp of last successful river data fetch', ["name"], registry=CUSTOM_REGISTRY)
_RIVER_LAST_FETCH_DURATION = Gauge('river_last_fetch_duration', 'Duration of last successful river API request (seconds)', ["name"], registry=CUSTOM_REGISTRY)
_RIVER_SUCCESSFUL_REQUESTS_TOTAL = Gauge('river_successful_requests_total', 'Total number of successful river API requests', ["name"], registry=CUSTOM_REGISTRY)
_RIVER_DATA_LAST_CHANGE = Gauge('river_data_last_change', 'Unix timestamp when river data last changed', ["name"], registry=CUSTOM_REGISTRY)

# Flow metrics
DORDOGNE_FLOW = _RIVERS_FLOW.labels(name="Dordogne")
LOT_FLOW = _RIVERS_FLOW.labels(name="Lot")

# Height metrics
DORDOGNE_HEIGHT = _RIVERS_HEIGHT.labels(name="Dordogne")
LOT_HEIGHT = _RIVERS_HEIGHT.labels(name="Lot")

# Health tracking variables
previous_river_data = {}  # river_name -> {'flow': value, 'height': value}
successful_river_requests = {}  # river_name -> count


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
        hauteur = measures["Serie"]["ObssHydro"][-1][1]

        elapsed = time.time() - start_time
        logging.debug(f"River API request for {river_code}/{serie} completed in {elapsed:.2f}s")

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


def update_river_data(river_name, station_code, flow_gauge, height_gauge):
    """Update flow and height data for a specific river"""
    current_time = time.time()

    # Get health monitoring metrics for this river
    last_fetch_time = _RIVER_LAST_FETCH_TIME.labels(name=river_name)
    last_fetch_duration = _RIVER_LAST_FETCH_DURATION.labels(name=river_name)
    successful_requests_total = _RIVER_SUCCESSFUL_REQUESTS_TOTAL.labels(name=river_name)
    data_last_change = _RIVER_DATA_LAST_CHANGE.labels(name=river_name)

    # Track successful request count
    total_requests = 0
    successful_durations = []

    # Get flow data
    flow_value, flow_duration = get_level(station_code, "Q")
    if flow_value is not None:
        flow_gauge.set(flow_value)
        logging.info(f"{river_name} flow: {flow_value} m3/s")
        total_requests += 1
        successful_durations.append(flow_duration)
    else:
        logging.warning(f"Failed to get {river_name} flow data")

    # Get height data
    height_value, height_duration = get_level(station_code, "H")
    if height_value is not None:
        height_gauge.set(height_value)
        logging.info(f"{river_name} height: {height_value} m")
        total_requests += 1
        successful_durations.append(height_duration)
    else:
        logging.warning(f"Failed to get {river_name} height data")

    # Update health metrics if we had any successful requests
    if total_requests > 0:
        # Update last fetch time and duration
        last_fetch_time.set(current_time)
        avg_duration = sum(successful_durations) / len(successful_durations)
        last_fetch_duration.set(avg_duration)

        # Update successful request count
        successful_river_requests[river_name] = successful_river_requests.get(river_name, 0) + total_requests
        successful_requests_total.set(successful_river_requests[river_name])

        # Check for data changes
        current_data = {'flow': flow_value, 'height': height_value}
        previous_data = previous_river_data.get(river_name, {})

        # Check if any value changed
        data_changed = False
        for key, value in current_data.items():
            if value is not None and previous_data.get(key) != value:
                data_changed = True
                logging.debug(f"{river_name} {key} changed: {previous_data.get(key)} -> {value}")

        if data_changed:
            data_last_change.set(current_time)
            previous_river_data[river_name] = current_data


def generate_hauteurs():
    """Update river flow and height metrics"""

    # Update Dordogne data (station P207002002)
    update_river_data("Dordogne", "P207002002", DORDOGNE_FLOW, DORDOGNE_HEIGHT)

    # Update Lot data (station O823153002)
    update_river_data("Lot", "O823153002", LOT_FLOW, LOT_HEIGHT)


def collect_all_data():
    """Collects all the river data currently set"""
    sensor_data = {}

    # Collect flow data
    flow_samples = _RIVERS_FLOW.collect()[0].samples
    for sample in flow_samples:
        river_name = sample.labels.get('name', 'unknown')
        sensor_data[f"river_flow_{river_name}"] = sample.value

    # Collect height data
    height_samples = _RIVERS_HEIGHT.collect()[0].samples
    for sample in height_samples:
        river_name = sample.labels.get('name', 'unknown')
        sensor_data[f"river_height_{river_name}"] = sample.value

    # Collect health metrics
    health_metrics = [_RIVER_LAST_FETCH_TIME, _RIVER_LAST_FETCH_DURATION,
                      _RIVER_SUCCESSFUL_REQUESTS_TOTAL, _RIVER_DATA_LAST_CHANGE]

    for metric in health_metrics:
        samples = metric.collect()[0].samples
        for sample in samples:
            river_name = sample.labels.get('name', 'unknown')
            metric_name = sample.name
            sensor_data[f"{metric_name}_{river_name}"] = sample.value

    return sensor_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--bind", metavar='ADDRESS', default='0.0.0.0', help="Specify alternate bind address [default: 0.0.0.0]")
    parser.add_argument("-p", "--port", metavar='PORT', default=8001, type=int, help="Specify alternate port [default: 8001]")
    parser.add_argument("-d", "--debug", metavar='DEBUG', type=str_to_bool, help="Turns on more verbose logging [default: false]")
    parser.add_argument("-i", "--interval", metavar='SECONDS', default=300, type=int, help="Update interval in seconds [default: 300]")
    args = parser.parse_args()

    if args.debug:
        DEBUG = True

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
            logging.info("Monitoring rivers - Flow & Height: Dordogne (P207002002), Lot (O823153002)")
            first = False

        if DEBUG:
            logging.info('River data: {}'.format(collect_all_data()))

        time.sleep(args.interval)