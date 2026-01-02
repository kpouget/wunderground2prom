#!/usr/bin/env python3
import os
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

# Flow metrics
DORDOGNE_FLOW = _RIVERS_FLOW.labels(name="Dordogne")
LOT_FLOW = _RIVERS_FLOW.labels(name="Lot")

# Height metrics
DORDOGNE_HEIGHT = _RIVERS_HEIGHT.labels(name="Dordogne")
LOT_HEIGHT = _RIVERS_HEIGHT.labels(name="Lot")


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
    try:
        # Add 30-second timeout to prevent hanging
        content = urllib.request.urlopen(url, timeout=30).read().decode('utf-8')
        measures = json.loads(content)
        hauteur = measures["Serie"]["ObssHydro"][-1][1]

        return hauteur
    except Exception as e:
        logging.warning(f"get_level(river_code={river_code}, series={serie}): {e.__class__.__name__}: {e}")
        return None


def generate_hauteurs():
    """Update river flow and height metrics"""

    # Dordogne flow (station P207002002)
    dordogne_flow = get_level("P207002002", "Q")
    if dordogne_flow is not None:
        DORDOGNE_FLOW.set(dordogne_flow)
        logging.info(f"Dordogne flow: {dordogne_flow} m3/s")
    else:
        logging.warning("Failed to get Dordogne flow data")

    # Dordogne height (station P207002002)
    dordogne_height = get_level("P207002002", "H")
    if dordogne_height is not None:
        DORDOGNE_HEIGHT.set(dordogne_height)
        logging.info(f"Dordogne height: {dordogne_height} m")
    else:
        logging.warning("Failed to get Dordogne height data")

    # Lot flow (station O823153002)
    lot_flow = get_level("O823153002", "Q")
    if lot_flow is not None:
        LOT_FLOW.set(lot_flow)
        logging.info(f"Lot flow: {lot_flow} m3/s")
    else:
        logging.warning("Failed to get Lot flow data")

    # Lot height (station O823153002)
    lot_height = get_level("O823153002", "H")
    if lot_height is not None:
        LOT_HEIGHT.set(lot_height)
        logging.info(f"Lot height: {lot_height} m")
    else:
        logging.warning("Failed to get Lot height data")


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