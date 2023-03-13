import json
import time
import os
import sys
import signal
import faulthandler

import requests
from attrdict import AttrDict
from qbittorrentapi import Client, TorrentStates
from qbittorrentapi.exceptions import APIConnectionError
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY
import logging
from pythonjsonlogger import jsonlogger


# Enable dumps on stderr in case of segfault
from requests.auth import HTTPBasicAuth

faulthandler.enable()
logger = logging.getLogger()


class QbittorrentMetricsCollector():


    def __init__(self, config):
        self.config = config

    def combine_url(self,endpoint):


        base_url = self.config["host"]
        base_url_port = self.config["port"]
        combined_url = base_url + ":" + base_url_port + endpoint

        return combined_url

    def collect(self):


        metrics = self.get_qbittorrent_metrics()

        for metric in metrics:
            name = metric["name"]
            value = metric["value"]
            help_text = metric.get("help", "")
            labels = metric.get("labels", {})
            metric_type = metric.get("type", "gauge")

            if metric_type == "counter":
                prom_metric = CounterMetricFamily(name, help_text, labels=labels.keys())
            else:
                prom_metric = GaugeMetricFamily(name, help_text, labels=labels.keys())
            prom_metric.add_metric(value=value, labels=labels.values())
            yield prom_metric

    def get_qbittorrent_metrics(self):
        metrics = []
        metrics.extend(self.get_qbittorrent_status_metrics())
        metrics.extend(self.get_qbittorrent_torrent_tags_metrics())

        return metrics

    def get_qbittorrent_status_metrics(self):
        response_stats = {}
        version = ""

        # Fetch data from API from Category "Server Info"
        token = self.config["token"]

        server_get_info_endpoint    = "/api/server-info"
        server_version_endpoint     = "/api/server-info/version"
        server_get_stats_endpoint   = "/api/server-info/stats"

        server_info_headers = {'Accept': 'application/json'}
        server_stats_headers = {'Accept': 'application/json',
                                'Authorization': f'Bearer {token}'}


        # Fetch server info

        try:
            # Fetch get server info
            logging.info(f"Fetching server stats")
            response_server_info = requests.request(
                "GET",
                self.combine_url(server_get_info_endpoint),
                headers=server_info_headers
            )

            # Fetch server verison

            response_server_version = requests.request(
                "GET",
                self.combine_url(server_version_endpoint),
                headers=server_info_headers
            )

            # Fetch Server Stats

            response_server_stats = requests.request(
                "GET",
                self.combine_url(server_get_stats_endpoint),
                headers=server_stats_headers,

            )



        except requests.exceptions.RequestException as e:
            logger.error(f"Couldn't get server info: {e.error_message}")


        return [
            {
                "name": f"{self.config['metrics_prefix']}_up",
                "value": bool(response_server_version),
                "labels": {"version": version},
                "help": "Immich Server Version Number",
            },
            {
                "name": f"{self.config['metrics_prefix']}_connected",
                "value": response_stats.get("connection_status", "") == "connected",
                "help": "Whether if server is connected or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_firewalled",
                "value": response_stats.get("connection_status", "") == "firewalled",
                "help": "Whether if server is under a firewall or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_dht_nodes",
                "value": response_stats.get("dht_nodes", 0),
                "help": "DHT nodes connected to",
            },
            {
                "name": f"{self.config['metrics_prefix']}_dl_info_data",
                "value": response_stats.get("dl_info_data", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter"
            },
            {
                "name": f"{self.config['metrics_prefix']}_up_info_data",
                "value": response_stats.get("up_info_data", 0),
                "help": "Data uploaded this session (bytes)",
                "type": "counter"
            },
        ]

    def get_qbittorrent_torrent_tags_metrics(self):
        try:
            categories = self.client.torrent_categories.categories
        except Exception as e:
            logger.error(f"Couldn't fetch categories: {e}")
            return []

        if not self.torrents:
            return []

        metrics = []
        categories.Uncategorized = AttrDict({'name': 'Uncategorized', 'savePath': ''})
        for category in categories:
            category_torrents = [t for t in self.torrents if t['category'] == category or (category == "Uncategorized" and t['category'] == "")]

            for status in self.TORRENT_STATUSES:
                status_prop = f"is_{status}"
                status_torrents = [
                    t for t in category_torrents if getattr(TorrentStates, status_prop).fget(TorrentStates(t['state']))
                ]
                metrics.append({
                    "name": f"{self.config['metrics_prefix']}_torrents_count",
                    "value": len(status_torrents),
                    "labels": {
                        "status": status,
                        "category": category,
                    },
                    "help": f"Number of torrents in status {status} under category {category}"
                })

        return metrics


class SignalHandler():
    def __init__(self):
        self.shutdownCount = 0

        # Register signal handler
        signal.signal(signal.SIGINT, self._on_signal_received)
        signal.signal(signal.SIGTERM, self._on_signal_received)

    def is_shutting_down(self):
        return self.shutdownCount > 0

    def _on_signal_received(self, signal, frame):
        if self.shutdownCount > 1:
            logger.warn("Forcibly killing exporter")
            sys.exit(1)
        logger.info("Exporter is shutting down")
        self.shutdownCount += 1

def get_config_value(key, default=""):
    input_path = os.environ.get("FILE__" + key, None)
    if input_path is not None:
        try:
            with open(input_path, "r") as input_file:
                return input_file.read().strip()
        except IOError as e:
            logger.error(f"Unable to read value for {key} from {input_path}: {str(e)}")

    return os.environ.get(key, default)


def main():
    # Init logger so it can be used
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime) %(levelname) %(message)",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel("INFO") # default until config is loaded

    config = {
        "token": get_config_value("IMMICH_API_TOKEN", ""),
        "host": get_config_value("QBITTORRENT_HOST", ""),
        "port": get_config_value("QBITTORRENT_PORT", ""),
        "username": get_config_value("QBITTORRENT_USER", ""),
        "password": get_config_value("QBITTORRENT_PASS", ""),
        "exporter_port": int(get_config_value("EXPORTER_PORT", "8000")),
        "log_level": get_config_value("EXPORTER_LOG_LEVEL", "INFO"),
        "metrics_prefix": get_config_value("METRICS_PREFIX", "qbittorrent"),
    }
    # set level once config has been loaded
    logger.setLevel(config["log_level"])

    # Register signal handler
    signal_handler = SignalHandler()


    if not config["host"]:
        logger.error("No host specified, please set QBITTORRENT_HOST environment variable")
        sys.exit(1)
    if not config["port"]:
        logger.error("No post specified, please set QBITTORRENT_PORT environment variable")
        sys.exit(1)

    # Register our custom collector
    logger.info("Exporter is starting up")
    REGISTRY.register(QbittorrentMetricsCollector(config))

    # Start server
    start_http_server(config["exporter_port"])
    logger.info(
        f"Exporter listening on port {config['exporter_port']}"
    )

    while not signal_handler.is_shutting_down():
        time.sleep(1)

    logger.info("Exporter has shutdown")
