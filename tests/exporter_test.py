import unittest
from unittest.mock import MagicMock, patch

from prometheus_client.metrics_core import CounterMetricFamily, GaugeMetricFamily

from qbittorrent_exporter.exporter import (
    Metric,
    MetricType,
    QbittorrentMetricsCollector,
)
from qbittorrentapi import TorrentStates


class TestQbittorrentMetricsCollector(unittest.TestCase):
    @patch("qbittorrent_exporter.exporter.Client")
    def setUp(self, mock_client):
        self.mock_client = mock_client
        self.config = {
            "host": "localhost",
            "port": "8080",
            "ssl": False,
            "url_base": "qbt/",
            "username": "user",
            "password": "pass",
            "verify_webui_certificate": False,
            "metrics_prefix": "qbittorrent",
        }
        self.torrentsState = [
            {"name": "Torrent DOWNLOADING 1", "state": TorrentStates.DOWNLOADING},
            {"name": "Torrent UPLOADING 1", "state": TorrentStates.UPLOADING},
            {"name": "Torrent DOWNLOADING 2", "state": TorrentStates.DOWNLOADING},
            {"name": "Torrent UPLOADING 2", "state": TorrentStates.UPLOADING},
        ]
        self.torrentsCategories = [
            {"name": "Torrent Movies 1", "category": "Movies"},
            {"name": "Torrent Music 1", "category": "Music"},
            {"name": "Torrent Movies 2", "category": "Movies"},
            {"name": "Torrent unknown", "category": ""},
            {"name": "Torrent Music 2", "category": "Music"},
            {"name": "Torrent Uncategorized 1", "category": "Uncategorized"},
        ]
        self.collector = QbittorrentMetricsCollector(self.config)

    def test_init(self):
        self.assertEqual(self.collector.config, self.config)
        self.mock_client.assert_called_once_with(
            host=f"http://{self.config['host']}:{self.config['port']}/qbt/",
            username=self.config["username"],
            password=self.config["password"],
            VERIFY_WEBUI_CERTIFICATE=self.config["verify_webui_certificate"],
        )

    def test_collect_gauge(self):
        mock_metric = Metric(
            name="test_gauge",
            metric_type=MetricType.GAUGE,
            help_text="Test Gauge",
            labels={"label1": "value1", "server": "localhost:8080"},
            value=10,
        )
        self.collector.get_qbittorrent_metrics = MagicMock(return_value=[mock_metric])

        result = next(self.collector.collect())

        self.assertIsInstance(result, GaugeMetricFamily)
        self.assertEqual(result.name, "test_gauge")
        self.assertEqual(result.documentation, "Test Gauge")
        self.assertEqual(
            result.samples[0].labels, {"label1": "value1", "server": "localhost:8080"}
        )
        self.assertEqual(result.samples[0].value, 10)

    def test_collect_counter(self):
        mock_metric = Metric(
            name="test_counter",
            metric_type=MetricType.COUNTER,
            help_text="Test Counter",
            labels={"label2": "value2", "server": "localhost:8080"},
            value=230,
        )
        self.collector.get_qbittorrent_metrics = MagicMock(return_value=[mock_metric])

        result = next(self.collector.collect())

        self.assertIsInstance(result, CounterMetricFamily)
        self.assertEqual(result.name, "test_counter")
        self.assertEqual(result.documentation, "Test Counter")
        self.assertEqual(
            result.samples[0].labels, {"label2": "value2", "server": "localhost:8080"}
        )
        self.assertEqual(result.samples[0].value, 230)

    def test_get_qbittorrent_metrics(self):
        metrics = self.collector.get_qbittorrent_metrics()
        self.assertNotEqual(len(metrics), 0)

    def test_fetch_categories(self):
        # Mock the client.torrent_categories.categories attribute
        self.collector.client.torrent_categories.categories = {
            "category1": {"name": "Category 1"},
            "category2": {"name": "Category 2"},
            "category3": {"name": "Category 3"},
        }

        categories = self.collector._fetch_categories()
        self.assertIsInstance(categories, dict)
        self.assertNotEqual(len(categories), 0)
        self.assertEqual(categories["category1"]["name"], "Category 1")
        self.assertEqual(categories["category2"]["name"], "Category 2")
        self.assertEqual(categories["category3"]["name"], "Category 3")

    def test_fetch_categories_exception(self):
        self.collector.client.torrent_categories.categories = Exception(
            "Error fetching categories"
        )
        categories = self.collector._fetch_categories()
        self.assertEqual(categories, {})

    def test_fetch_torrents_success(self):
        # Mock the return value of self.client.torrents.info()
        self.collector.client.torrents.info.return_value = [
            {"name": "Torrent 1", "size": 100},
            {"name": "Torrent 2", "size": 200},
            {"name": "Torrent 3", "size": 300},
        ]

        expected_result = [
            {"name": "Torrent 1", "size": 100},
            {"name": "Torrent 2", "size": 200},
            {"name": "Torrent 3", "size": 300},
        ]

        result = self.collector._fetch_torrents()
        self.assertEqual(result, expected_result)

    def test_fetch_torrents_exception(self):
        # Mock an exception being raised by self.client.torrents.info()
        self.collector.client.torrents.info.side_effect = Exception("Connection error")

        expected_result = []

        result = self.collector._fetch_torrents()
        self.assertEqual(result, expected_result)

    def test_filter_torrents_by_state(self):
        expected = [
            {"name": "Torrent DOWNLOADING 1", "state": TorrentStates.DOWNLOADING},
            {"name": "Torrent DOWNLOADING 2", "state": TorrentStates.DOWNLOADING},
        ]
        result = self.collector._filter_torrents_by_state(
            TorrentStates.DOWNLOADING, self.torrentsState
        )
        self.assertEqual(result, expected)

        expected = [
            {"name": "Torrent UPLOADING 1", "state": TorrentStates.UPLOADING},
            {"name": "Torrent UPLOADING 2", "state": TorrentStates.UPLOADING},
        ]
        result = self.collector._filter_torrents_by_state(
            TorrentStates.UPLOADING, self.torrentsState
        )
        self.assertEqual(result, expected)

        expected = []
        result = self.collector._filter_torrents_by_state(
            TorrentStates.ERROR, self.torrentsState
        )
        self.assertEqual(result, expected)

    def test_filter_torrents_by_category(self):
        expected_result = [
            {"name": "Torrent Movies 1", "category": "Movies"},
            {"name": "Torrent Movies 2", "category": "Movies"},
        ]
        result = self.collector._filter_torrents_by_category(
            "Movies", self.torrentsCategories
        )
        self.assertEqual(result, expected_result)

        expected_result = [
            {"name": "Torrent unknown", "category": ""},
            {"name": "Torrent Uncategorized 1", "category": "Uncategorized"},
        ]
        result = self.collector._filter_torrents_by_category(
            "Uncategorized", self.torrentsCategories
        )
        self.assertEqual(result, expected_result)

        expected_result = []
        result = self.collector._filter_torrents_by_category(
            "Books", self.torrentsCategories
        )
        self.assertEqual(result, expected_result)

    def test_construct_metric_with_valid_state_and_category(self):
        state = "downloading"
        category = "movies"
        count = 10

        metric = self.collector._construct_metric(state, category, count)

        self.assertEqual(metric.name, "qbittorrent_torrents_count")
        self.assertEqual(metric.value, count)
        self.assertEqual(metric.labels["status"], state)
        self.assertEqual(metric.labels["category"], category)
        self.assertEqual(
            metric.help_text,
            f"Number of torrents in status {state} under category {category}",
        )

    def test_construct_metric_with_empty_state_and_category(self):
        state = ""
        category = ""
        count = 5

        metric = self.collector._construct_metric(state, category, count)

        self.assertEqual(metric.name, "qbittorrent_torrents_count")
        self.assertEqual(metric.value, count)
        self.assertEqual(metric.labels["status"], state)
        self.assertEqual(metric.labels["category"], category)
        self.assertEqual(
            metric.help_text, "Number of torrents in status  under category "
        )

    def test_get_qbittorrent_status_metrics(self):
        self.collector.client.sync_maindata.return_value = {
            "server_state": {"connection_status": "connected"}
        }
        self.collector.client.app.version = "1.2.3"

        expected_metrics = [
            Metric(
                name="qbittorrent_up",
                value=True,
                labels={"version": "1.2.3", "server": "localhost:8080/qbt/"},
                help_text=(
                    "Whether the qBittorrent server is answering requests from this"
                    " exporter. A `version` label with the server version is added."
                ),
            ),
            Metric(
                name="qbittorrent_connected",
                value=True,
                labels={"server": "localhost:8080/qbt/"},
                help_text=(
                    "Whether the qBittorrent server is connected to the Bittorrent"
                    " network."
                ),
            ),
            Metric(
                name="qbittorrent_firewalled",
                value=False,
                labels={"server": "localhost:8080/qbt/"},
                help_text=(
                    "Whether the qBittorrent server is connected to the Bittorrent"
                    " network but is behind a firewall."
                ),
            ),
            Metric(
                name="qbittorrent_dht_nodes",
                value=0,
                labels={"server": "localhost:8080/qbt/"},
                help_text="Number of DHT nodes connected to.",
            ),
            Metric(
                name="qbittorrent_dl_info_data",
                value=0,
                labels={"server": "localhost:8080/qbt/"},
                help_text="Data downloaded since the server started, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name="qbittorrent_up_info_data",
                value=0,
                labels={"server": "localhost:8080/qbt/"},
                help_text="Data uploaded since the server started, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name="qbittorrent_alltime_dl",
                value=0,
                labels={"server": "localhost:8080/qbt/"},
                help_text="Total historical data downloaded, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
            Metric(
                name="qbittorrent_alltime_ul",
                value=0,
                labels={"server": "localhost:8080/qbt/"},
                help_text="Total historical data uploaded, in bytes.",
                metric_type=MetricType.COUNTER,
            ),
        ]

        metrics = self.collector._get_qbittorrent_status_metrics()
        self.assertEqual(metrics, expected_metrics)

    def test_server_string_with_different_settings(self):
        self.assertEqual(self.collector.server, "localhost:8080/qbt/")
        self.assertEqual(self.collector.connection_string, "http://localhost:8080/qbt/")

        config = {
            "host": "qbittorrent.example.com",
            "port": "8081",
            "ssl": False,
            "url_base": "qbittorrent/",
            "username": "user",
            "password": "pass",
            "verify_webui_certificate": False,
            "metrics_prefix": "qbittorrent",
        }
        collector = QbittorrentMetricsCollector(config)
        self.assertEqual(collector.server, "qbittorrent.example.com:8081/qbittorrent/")
        self.assertEqual(collector.connection_string, "http://qbittorrent.example.com:8081/qbittorrent/")

        config = {
            "host": "qbittorrent2.example.com",
            "port": "8084",
            "ssl": True,
            "url_base": "",
            "username": "user",
            "password": "pass",
            "verify_webui_certificate": True,
            "metrics_prefix": "qbittorrent",
        }
        collector = QbittorrentMetricsCollector(config)
        self.assertEqual(collector.server, "qbittorrent2.example.com:8084")
        self.assertEqual(collector.connection_string, "https://qbittorrent2.example.com:8084")

        config = {
            "host": "qbittorrent3.example.com",
            "port": "443",
            "ssl": False,  # Will be enforced to True because port is 443
            "url_base": "server/",
            "username": "user",
            "password": "pass",
            "verify_webui_certificate": True,
            "metrics_prefix": "qbittorrent",
        }
        collector = QbittorrentMetricsCollector(config)
        self.assertEqual(collector.server, "qbittorrent3.example.com:443/server/")
        self.assertEqual(collector.connection_string, "https://qbittorrent3.example.com:443/server/")
