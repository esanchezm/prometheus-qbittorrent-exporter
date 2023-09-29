import time
import os
import sys
import signal
import faulthandler
from qbittorrentapi import Client, TorrentStates
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY
import logging
from pythonjsonlogger import jsonlogger
from enum import StrEnum, auto
from typing import Iterable, Any
from dataclasses import dataclass, field

# Enable dumps on stderr in case of segfault
faulthandler.enable()
logger = logging.getLogger()


class TorrentStatuses(StrEnum):
    """
    Represents possible torrent states.
    """

    CHECKING = auto()
    COMPLETE = auto()
    ERRORED = auto()
    PAUSED = auto()
    UPLOADING = auto()


class MetricType(StrEnum):
    """
    Represents possible metric types (used in this project).
    """

    GAUGE = auto()
    COUNTER = auto()


@dataclass
class Metric:
    """
    Contains data and metadata about a single counter or gauge.
    """

    name: str
    value: Any
    labels: dict[str, str] = field(default_factory=lambda: {})  # Default to empty dict
    help_text: str = ""
    metric_type: MetricType = MetricType.GAUGE


class QbittorrentMetricsCollector:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.client = Client(
            host=config["host"],
            port=config["port"],
            username=config["username"],
            password=config["password"],
            VERIFY_WEBUI_CERTIFICATE=config["verify_webui_certificate"],
        )

    def collect(self) -> Iterable[GaugeMetricFamily | CounterMetricFamily]:
        """
        Gets Metric objects representing the current state of qbittorrent and yields
        Prometheus gauges.
        """
        metrics: list[Metric] = self.get_qbittorrent_metrics()

        for metric in metrics:
            if metric.metric_type == MetricType.COUNTER:
                prom_metric = CounterMetricFamily(
                    metric.name, metric.help_text, labels=list(metric.labels.keys())
                )
            else:
                prom_metric = GaugeMetricFamily(
                    metric.name, metric.help_text, labels=list(metric.labels.keys())
                )
            prom_metric.add_metric(
                value=metric.value, labels=list(metric.labels.values())
            )
            yield prom_metric

    def get_qbittorrent_metrics(self) -> list[Metric]:
        """
        Calls and combines qbittorrent state metrics with torrent metrics.
        """
        metrics: list[Metric] = []
        metrics.extend(self._get_qbittorrent_status_metrics())
        metrics.extend(self._get_qbittorrent_torrent_tags_metrics())

        return metrics

    def _get_qbittorrent_status_metrics(self) -> list[Metric]:
        """
        Returns metrics about the state of the qbittorrent server.
        """
        response: dict[str, Any] = {}
        version: str = ""

        # Fetch data from API
        try:
            response = self.client.transfer.info
            version = self.client.app.version
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")

        return [
            Metric(
                name=f"{self.config['metrics_prefix']}_up",
                value=bool(response),
                labels={"version": version},
                help_text=(
                    "Whether the qBittorrent server is answering requests from this"
                    " exporter. A `version` label with the server version is added."
                ),
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_connected",
                value=response.get("connection_status", "") == "connected",
                labels={},  # no labels in the example
                help_text=(
                    "Whether the qBittorrent server is connected to the Bittorrent"
                    " network."
                ),
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_firewalled",
                value=response.get("connection_status", "") == "firewalled",
                labels={},  # no labels in the example
                help_text=(
                    "Whether the qBittorrent server is connected to the Bittorrent"
                    " network but is behind a firewall."
                ),
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_dht_nodes",
                value=response.get("dht_nodes", 0),
                labels={},  # no labels in the example
                help_text="Number of DHT nodes connected to.",
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_dl_info_data",
                value=response.get("dl_info_data", 0),
                labels={},  # no labels in the example
                help_text="Data downloaded since the server started, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_up_info_data",
                value=response.get("up_info_data", 0),
                labels={},  # no labels in the example
                help_text="Data uploaded since the server started, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
        ]

    def _get_qbittorrent_torrent_tags_metrics(self) -> list[Metric]:
        """
        Returns Metric object containing number of torrents for each `category` and
        `status`.
        """
        try:
            categories = self.client.torrent_categories.categories
            torrents = self.client.torrents.info()
        except Exception as e:
            logger.error(f"Couldn't fetch torrent info: {e}")
            return []

        metrics: list[Metric] = []

        # Match torrents to categories
        for category in categories:
            category_torrents: list = [
                torrent
                for torrent in torrents
                if torrent["category"] == category
                or (category == "Uncategorized" and torrent["category"] == "")
            ]

            # Match qbittorrentapi torrent state to local TorrenStatuses
            for status in TorrentStatuses:
                proposed_status: str = f"is_{status.value}"
                status_torrents = [
                    torrent
                    for torrent in category_torrents
                    if getattr(TorrentStates, proposed_status).fget(
                        TorrentStates(torrent["state"])
                    )
                ]
                metrics.append(
                    Metric(
                        name=f"{self.config['metrics_prefix']}_torrents_count",
                        value=len(status_torrents),
                        labels={
                            "status": status.value,
                            "category": category,
                        },
                        help_text=(
                            f"Number of torrents in status {status.value} under"
                            f" category {category}"
                        ),
                    )
                )

        return metrics


class SignalHandler:
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
        "%(asctime) %(levelname) %(message)", datefmt="%Y-%m-%d %H:%M:%S"
    )
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel("INFO")  # default until config is loaded

    config = {
        "host": get_config_value("QBITTORRENT_HOST", ""),
        "port": get_config_value("QBITTORRENT_PORT", ""),
        "username": get_config_value("QBITTORRENT_USER", ""),
        "password": get_config_value("QBITTORRENT_PASS", ""),
        "exporter_port": int(get_config_value("EXPORTER_PORT", "8000")),
        "log_level": get_config_value("EXPORTER_LOG_LEVEL", "INFO"),
        "metrics_prefix": get_config_value("METRICS_PREFIX", "qbittorrent"),
        "verify_webui_certificate": (
            get_config_value("VERIFY_WEBUI_CERTIFICATE", "True") == "True"
        ),
    }
    # set level once config has been loaded
    logger.setLevel(config["log_level"])

    # Register signal handler
    signal_handler = SignalHandler()

    if not config["host"]:
        logger.error(
            "No host specified, please set QBITTORRENT_HOST environment variable"
        )
        sys.exit(1)
    if not config["port"]:
        logger.error(
            "No port specified, please set QBITTORRENT_PORT environment variable"
        )
        sys.exit(1)

    # Register our custom collector
    logger.info("Exporter is starting up")
    REGISTRY.register(QbittorrentMetricsCollector(config))  # type: ignore

    # Start server
    start_http_server(config["exporter_port"])
    logger.info(f"Exporter listening on port {config['exporter_port']}")

    while not signal_handler.is_shutting_down():
        time.sleep(1)

    logger.info("Exporter has shutdown")


if __name__ == "__main__":
    main()
