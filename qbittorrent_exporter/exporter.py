import faulthandler
import logging
import os
import signal
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, CounterMetricFamily, GaugeMetricFamily
from pythonjsonlogger import jsonlogger
from qbittorrentapi import Client, TorrentStates

# Enable dumps on stderr in case of segfault
faulthandler.enable()
logger = logging.getLogger()

# Seconds to wait for qBittorrent to connect and to send each response, used
# for every metric request. qbittorrent-api tries a failed request twice, so a
# scrape against an unresponsive server ends after about twice this value,
# inside Prometheus' default scrape timeout (10 s), instead of running on in
# the background.
DEFAULT_QBITTORRENT_TIMEOUT = 4.0


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
    labels: dict[str, str] = field(default_factory=dict)
    help_text: str = ""
    metric_type: MetricType = MetricType.GAUGE


class QbittorrentMetricsCollector:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.server = f"{config['host']}:{config['port']}"
        self.protocol = "http"

        if config["url_base"]:
            self.server = f"{self.server}/{config['url_base'].lstrip('/')}"
        if config["ssl"] or config["port"] == "443":
            self.protocol = "https"
        self.connection_string = f"{self.protocol}://{self.server}"

    def _create_client(self) -> Client:
        client_args: dict[str, Any] = {
            "host": self.connection_string,
            "VERIFY_WEBUI_CERTIFICATE": self.config["verify_webui_certificate"],
            # The scheme comes from QBITTORRENT_SSL (or port 443). Without this,
            # qbittorrent-api probes HTTPS and HTTP again whenever a request
            # fails, which multiplies the time a scrape waits for a server that
            # does not answer, and can silently fall back to plain HTTP.
            "FORCE_SCHEME_FROM_HOST": True,
            "REQUESTS_ARGS": {
                "timeout": self.config.get("timeout", DEFAULT_QBITTORRENT_TIMEOUT)
            },
        }

        # qBittorrent 5.2+ supports API key auth via bearer tokens
        if self.config.get("api_key"):
            logger.debug("Utilizing API key based authentication")
            client_args["EXTRA_HEADERS"] = {
                "Authorization": f"Bearer {self.config['api_key']}"
            }
        else:
            logger.debug("Utilizing username and password based authentication")
            client_args["username"] = self.config["username"]
            client_args["password"] = self.config["password"]

        return Client(**client_args)

    def collect(self) -> Iterable[GaugeMetricFamily | CounterMetricFamily]:
        """
        Yields Prometheus gauges and counters from metrics collected from qbittorrent.
        """
        client = self._create_client()
        try:
            maindata, version = self._fetch_maindata(client)
            for metric in self._get_qbittorrent_status_metrics(maindata, version):
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

            # The server did not answer: skip the torrent metrics instead of
            # making more requests that would wait for it too.
            if not maindata.get("server_state"):
                return

            torrents = self._get_torrents(maindata)
            yield from self._get_qbittorrent_by_torrent_metric_gauges(torrents)

            yield self._get_qbittorrent_torrent_tags_metrics_gauge(
                self._get_categories(maindata), torrents
            )
        finally:
            # Release the WebUI session before discarding this scrape's client.
            # Bearer-token authentication does not create a WebUI session, and
            # a client that never logged in (the server did not answer) has
            # none to release.
            if not self.config.get("api_key") and client._SID:
                try:
                    # Bypass auth_log_out's preflight: a failed session check
                    # must not prevent sending logout for this scrape's session.
                    client._post(
                        _name="auth", _method="logout", requests_args={"timeout": 5}
                    )
                except Exception as e:
                    logger.error(f"Couldn't log out of qBittorrent: {e}")

    def _get_qbittorrent_by_torrent_metric_gauges(
        self, torrents: list[dict]
    ) -> list[GaugeMetricFamily]:
        if not self.config.get("export_metrics_by_torrent", False):
            return []

        torrent_size_gauge = GaugeMetricFamily(
            f"{self.config['metrics_prefix']}_torrent_size",
            "Size of the torrent",
            labels=["name", "category", "server"],
        )

        torrent_downloaded_gauge = GaugeMetricFamily(
            f"{self.config['metrics_prefix']}_torrent_downloaded",
            "Downloaded data for the torrent",
            labels=["name", "category", "server"],
        )

        for torrent in torrents:
            torrent_size_gauge.add_metric(
                value=torrent["size"],
                labels=[torrent["name"], torrent["category"], self.server],
            )
            torrent_downloaded_gauge.add_metric(
                value=torrent["downloaded"],
                labels=[torrent["name"], torrent["category"], self.server],
            )

        return [torrent_size_gauge, torrent_downloaded_gauge]

    def _fetch_maindata(self, client: Client) -> tuple[dict[str, Any], str]:
        """
        Fetches the server state, categories and torrents in one request, plus
        the server version. Returns an empty dict when the server does not answer.
        """
        try:
            maindata = dict(client.sync_maindata())
            version = client.app.version
        except Exception as e:
            logger.error(f"Couldn't get server info: {e}")
            return {}, ""
        return maindata, version

    def _get_qbittorrent_status_metrics(
        self, maindata: dict[str, Any], version: str
    ) -> list[Metric]:
        """
        Returns metrics about the state of the qbittorrent server.
        """
        server_state = maindata.get("server_state") or {}

        return [
            Metric(
                name=f"{self.config['metrics_prefix']}_up",
                value=bool(server_state),
                labels={"version": version, "server": self.server},
                help_text=(
                    "Whether the qBittorrent server is answering requests from this"
                    " exporter. A `version` label with the server version is added."
                ),
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_connected",
                value=server_state.get("connection_status", "") == "connected",
                labels={"server": self.server},
                help_text=(
                    "Whether the qBittorrent server is connected to the Bittorrent"
                    " network."
                ),
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_firewalled",
                value=server_state.get("connection_status", "") == "firewalled",
                labels={"server": self.server},
                help_text=(
                    "Whether the qBittorrent server is connected to the Bittorrent"
                    " network but is behind a firewall."
                ),
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_dht_nodes",
                value=server_state.get("dht_nodes", 0),
                labels={"server": self.server},
                help_text="Number of DHT nodes connected to.",
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_total_peer_connections",
                value=server_state.get("total_peer_connections", 0),
                labels={"server": self.server},
                help_text="Total number of peer connections.",
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_dl_info_data",
                value=server_state.get("dl_info_data", 0),
                labels={"server": self.server},
                help_text="Data downloaded since the server started, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_up_info_data",
                value=server_state.get("up_info_data", 0),
                labels={"server": self.server},
                help_text="Data uploaded since the server started, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_alltime_dl",
                value=server_state.get("alltime_dl", 0),
                labels={"server": self.server},
                help_text="Total historical data downloaded, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name=f"{self.config['metrics_prefix']}_alltime_ul",
                value=server_state.get("alltime_ul", 0),
                labels={"server": self.server},
                help_text="Total historical data uploaded, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
        ]

    def _get_categories(self, maindata: dict[str, Any]) -> dict:
        """Returns the categories from a sync/maindata response."""
        categories = maindata.get("categories") or {}
        return {key: dict(value) for key, value in categories.items()}

    def _get_torrents(self, maindata: dict[str, Any]) -> list[dict]:
        """Returns the torrents from a sync/maindata response."""
        torrents = maindata.get("torrents") or {}
        return [dict(torrent) for torrent in torrents.values()]

    def _filter_torrents_by_category(
        self, category: str, torrents: list[dict]
    ) -> list[dict]:
        """Filters torrents by the given category."""
        return [
            torrent
            for torrent in torrents
            if torrent["category"] == category
            or (category == "Uncategorized" and torrent["category"] == "")
        ]

    def _filter_torrents_by_state(
        self, state: TorrentStates, torrents: list[dict]
    ) -> list[dict]:
        """Filters torrents by the given state."""
        return [torrent for torrent in torrents if torrent["state"] == state.value]

    def _get_qbittorrent_torrent_tags_metrics_gauge(
        self, categories: dict, torrents: list[dict]
    ) -> GaugeMetricFamily:
        categories = {**categories}
        categories["Uncategorized"] = {"name": "Uncategorized", "savePath": ""}

        torrents_count_gauge = GaugeMetricFamily(
            f"{self.config['metrics_prefix']}_torrents_count",
            "Number of torrents",
            labels=["status", "category", "server"],
        )

        for category in categories:
            category_torrents = self._filter_torrents_by_category(category, torrents)
            for state in TorrentStates:
                state_torrents = self._filter_torrents_by_state(
                    state, category_torrents
                )
                torrents_count_gauge.add_metric(
                    value=len(state_torrents),
                    labels=[state.value, category, self.server],
                )

        return torrents_count_gauge


class ShutdownSignalHandler:
    def __init__(self):
        self.shutdown_count: int = 0

        # Register signal handler
        signal.signal(signal.SIGINT, self._on_signal_received)
        signal.signal(signal.SIGTERM, self._on_signal_received)

    def is_shutting_down(self):
        return self.shutdown_count > 0

    def _on_signal_received(self, signal, frame):
        if self.shutdown_count >= 1:
            logger.warning("Forcibly killing exporter")
            sys.exit(1)
        logger.info("Exporter is shutting down")
        self.shutdown_count += 1


def _get_config_value(key: str, default: str = "") -> str:
    input_path = os.environ.get("FILE__" + key, None)
    if input_path is not None:
        try:
            with open(input_path, "r") as input_file:
                return input_file.read().strip()
        except OSError as e:
            logger.error(f"Unable to read value for {key} from {input_path}: {e!s}")
            sys.exit(1)

    return os.environ.get(key, default)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def _validate_log_level(level: str) -> str:
    level = level.strip().upper()
    if level not in logging.getLevelNamesMapping():
        logger.error(f"Invalid EXPORTER_LOG_LEVEL: {level}")
        sys.exit(1)
    return level


def get_config() -> dict:
    """Loads all config values."""
    try:
        exporter_port = int(_get_config_value("EXPORTER_PORT", "8000"))
    except ValueError:
        logger.error("Invalid EXPORTER_PORT, must be an integer")
        sys.exit(1)
    if not 1 <= exporter_port <= 65535:
        logger.error("Invalid EXPORTER_PORT, must be between 1 and 65535")
        sys.exit(1)

    try:
        timeout = float(
            _get_config_value("QBITTORRENT_TIMEOUT", str(DEFAULT_QBITTORRENT_TIMEOUT))
        )
    except ValueError:
        logger.error("Invalid QBITTORRENT_TIMEOUT, must be a number of seconds")
        sys.exit(1)
    if not timeout > 0:
        logger.error("Invalid QBITTORRENT_TIMEOUT, must be greater than 0")
        sys.exit(1)

    return {
        "host": _get_config_value("QBITTORRENT_HOST", ""),
        "port": _get_config_value("QBITTORRENT_PORT", ""),
        "ssl": _parse_bool(_get_config_value("QBITTORRENT_SSL", "False")),
        "url_base": _get_config_value("QBITTORRENT_URL_BASE", ""),
        "username": _get_config_value("QBITTORRENT_USER", ""),
        "password": _get_config_value("QBITTORRENT_PASS", ""),
        "api_key": _get_config_value("QBITTORRENT_API_KEY", ""),
        "timeout": timeout,
        "exporter_address": _get_config_value("EXPORTER_ADDRESS", "0.0.0.0"),
        "exporter_port": exporter_port,
        "log_level": _get_config_value("EXPORTER_LOG_LEVEL", "INFO"),
        "metrics_prefix": _get_config_value("METRICS_PREFIX", "qbittorrent"),
        "export_metrics_by_torrent": _parse_bool(
            _get_config_value("EXPORT_METRICS_BY_TORRENT", "False")
        ),
        "verify_webui_certificate": _parse_bool(
            _get_config_value("VERIFY_WEBUI_CERTIFICATE", "True")
        ),
    }


def main():
    # Init logger so it can be used
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime) %(levelname) %(message)", datefmt="%Y-%m-%d %H:%M:%S"
    )
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel("INFO")  # default until config is loaded

    config = get_config()

    # set level once config has been loaded
    logger.setLevel(_validate_log_level(config["log_level"]))

    # Register signal handler
    signal_handler = ShutdownSignalHandler()

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
    start_http_server(config["exporter_port"], config["exporter_address"])
    logger.info(
        f"Exporter listening on {config['exporter_address']}:{config['exporter_port']}"
    )

    while not signal_handler.is_shutting_down():
        time.sleep(1)

    logger.info("Exporter has shutdown")


if __name__ == "__main__":
    main()
