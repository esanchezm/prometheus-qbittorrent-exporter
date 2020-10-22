import time
import os
import sys
import signal
import faulthandler
from attrdict import AttrDict
from qbittorrentapi import Client, TorrentStates
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY
import logging
from pythonjsonlogger import jsonlogger


# Enable dumps on stderr in case of segfault
faulthandler.enable()
logger = None


class QbittorrentMetricsCollector():
    TORRENT_STATUSES = [
        "downloading",
        "uploading",
        "complete",
        "checking",
        "errored",
        "paused",
    ]

    def __init__(self, config):
        self.config = config
        self.torrents = None
        self.client = Client(
            host=config["host"],
            port=config["port"],
            username=config["username"],
            password=config["password"],
        )

    def collect(self):
        try:
            self.torrents = self.client.torrents.info()
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")

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
        # Fetch data from API
        try:
            response = self.client.transfer.info
            version = self.client.app.version
            self.torrents = self.client.torrents.info()
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")
            response = None
            version = ""

        return [
            {
                "name": f"{self.config['metrics_prefix']}_up",
                "value": response is not None,
                "labels": {"version": version},
                "help": "Whether if server is alive or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_connected",
                "value": response.get("connection_status", "") == "connected",
                "help": "Whether if server is connected or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_firewalled",
                "value": response.get("connection_status", "") == "firewalled",
                "help": "Whether if server is under a firewall or not",
            },
            {
                "name": f"{self.config['metrics_prefix']}_dht_nodes",
                "value": response.get("dht_nodes", 0),
                "help": "DHT nodes connected to",
            },
            {
                "name": f"{self.config['metrics_prefix']}_dl_info_data",
                "value": response.get("dl_info_data", 0),
                "help": "Data downloaded this session (bytes)",
                "type": "counter"
            },
            {
                "name": f"{self.config['metrics_prefix']}_up_info_data",
                "value": response.get("up_info_data", 0),
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
        self.shutdown = False

        # Register signal handler
        signal.signal(signal.SIGINT, self._on_signal_received)
        signal.signal(signal.SIGTERM, self._on_signal_received)

    def is_shutting_down(self):
        return self.shutdown

    def _on_signal_received(self, signal, frame):
        logger.info("Exporter is shutting down")
        self.shutdown = True


def main():
    config = {
        "host": os.environ.get("QBITTORRENT_HOST", ""),
        "port": os.environ.get("QBITTORRENT_PORT", ""),
        "username": os.environ.get("QBITTORRENT_USER", ""),
        "password": os.environ.get("QBITTORRENT_PASS", ""),
        "exporter_port": int(os.environ.get("EXPORTER_PORT", "8000")),
        "log_level": os.environ.get("EXPORTER_LOG_LEVEL", "INFO"),
        "metrics_prefix": os.environ.get("METRICS_PREFIX", "qbittorrent"),
    }

    # Register signal handler
    signal_handler = SignalHandler()

    # Init logger
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime) %(levelname) %(message)",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logHandler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.addHandler(logHandler)
    logger.setLevel(config["log_level"])

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
