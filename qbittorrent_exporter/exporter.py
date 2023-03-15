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
faulthandler.enable()
logger = logging.getLogger()


class QbittorrentMetricsCollector():

    def __init__(self, config):
        self.config = config

    def collect(self):

        metrics = self.get_immich_metrics()

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

    def get_immich_metrics(self):
        metrics = []
        metrics.extend(self.get_immich_server_version_number())
        metrics.extend(self.get_immich_server_info())
        metrics.extend(self.get_immich_users_stat())

        return metrics

    def get_immich_users_stat(self):


        try:
            endpoint_user_stats = "/api/server-info/stats"
            response_user_stats = requests.request(
                "GET",
                self.combine_url(endpoint_user_stats),
                headers={'Accept': 'application/json',
                         "x-api-key": self.config["token"]}
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Couldn't get server version: {e}")

        metrics = []
        userCount = len(response_user_stats.json()["usageByUser"])

        #userCount
        metrics.append(
            {
                "name": f"{self.config['metrics_prefix']}_user_count",
                "value": userCount,
                "help": "number of users on the immich server"
            }
        )

        #Photos
        usersDatas = response_user_stats.json()["usageByUser"]  # TODO rename usersdatas in the future
        for x in range(0,userCount):                              # TODO rename usersdatas in the future
            metrics.append(

                    {
                    "name": f"{self.config['metrics_prefix']}_photos_by_user",
                    "value": usersDatas[x]['photos'],
                    "labels": {
                        "firstName": usersDatas[x]["userFirstName"],

                    },
                    "help": f"Number of photos by user {usersDatas[x]['userFirstName']} "

                    }
                )

        #videos
        for x in range(0,userCount):
            metrics.append(
                    {
                    "name": f"{self.config['metrics_prefix']}_videos_by_user",
                    "value": usersDatas[x]['videos'],
                    "labels": {
                        "firstName": usersDatas[x]["userFirstName"],

                    },
                    "help": f"Number of photos by user {usersDatas[x]['userFirstName']} "

                    }
                )
        #usage
        for x in range(0,userCount):
            metrics.append(
                    {
                    "name": f"{self.config['metrics_prefix']}_usage_by_user",
                    "value": (usersDatas[x]['usage']),
                    "labels": {
                        "firstName": usersDatas[x]["userFirstName"],

                    },
                    "help": f"Number of photos by user {usersDatas[x]['userFirstName']} "

                    }
                )

        return metrics

    def get_immich_server_info(self):

        try:
            endpoint_server_info = "/api/server-info"
            response_server_info = requests.request(
                "GET",
                self.combine_url(endpoint_server_info),
                headers={'Accept': 'application/json'}
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Couldn't get server version: {e}")





        return [
            {
                "name": f"{self.config['metrics_prefix']}_diskAvailable",
                "value": (response_server_info.json()["diskAvailableRaw"]),
                "help": "Available space on disk",
            },
            {
                "name": f"{self.config['metrics_prefix']}_totalDiskSize",
                "value": (response_server_info.json()["diskSizeRaw"]),
                "help": "tota disk size",
                #"type": "counter"
            },
            {
                "name": f"{self.config['metrics_prefix']}_diskUse",
                "value": (response_server_info.json()["diskUseRaw"]),
                "help": "disk space in use",
                #"type": "counter"
            },
            {
                "name": f"{self.config['metrics_prefix']}_diskUsagePercentage",
                "value": (response_server_info.json()["diskUsagePercentage"]),
                "help": "disk usage in percent",
                # "type": "counter"
            }
        ]

    def get_immich_server_version_number(self):

        server_version_endpoint = "/api/server-info/version"

        try:

            response_server_version = requests.request(
                "GET",
                self.combine_url(server_version_endpoint),
                headers={'Accept': 'application/json'}
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Couldn't get server version: {e}")

        server_version_number = ( str(response_server_version.json()["major"]) + "." +
                                  str(response_server_version.json()["minor"]) + "." +
                                  str(response_server_version.json()["patch"])
                                  )


        return [
            {
                "name": f"{self.config['metrics_prefix']}_version_number",
                "value": bool(server_version_number),
                "help": "server version number",
                "labels": {"version": server_version_number}

            }
        ]

    def combine_url(self, api_endpoint):
        base_url = self.config["immich_host"]
        base_url_port = self.config["immich_port"]
        combined_url = base_url + ":" + base_url_port + api_endpoint

        return combined_url



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
            logger.warning("Forcibly killing exporter")
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
    logger.setLevel("INFO")  # default until config is loaded

    config = {
        "immich_host": get_config_value("IMMICH_HOST", ""),
        "immich_port": get_config_value("IMMICH_PORT", ""),
        "token": get_config_value("IMMICH_API_TOKEN", ""),
        "exporter_port": int(get_config_value("EXPORTER_PORT", "8000")),
        "log_level": get_config_value("EXPORTER_LOG_LEVEL", "INFO"),
        "metrics_prefix": get_config_value("METRICS_PREFIX", "immich"),
    }
    # set level once config has been loaded
    logger.setLevel(config["log_level"])

    # Register signal handler
    signal_handler = SignalHandler()

    if not config["immich_host"]:
        logger.error("No host specified, please set IMMICH_HOST environment variable")
        sys.exit(1)
    if not config["token"]:
        logger.error("No token specified, please set IMMICH_API_TOKEN environment variable")
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
