import unittest
from unittest.mock import MagicMock, patch

from prometheus_client.metrics_core import CounterMetricFamily, GaugeMetricFamily
from qbittorrentapi import TorrentStates

from qbittorrent_exporter.exporter import (
    Metric,
    MetricType,
    QbittorrentMetricsCollector,
)


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
            "export_metrics_by_torrent": True,
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

    def test_collect_by_torrent_metric_gauges(self):
        # Mock the return value of self.client.torrents.info()
        self.collector.client.torrents.info.return_value = [
            {
                "name": "Torrent 1",
                "size": 100,
                "category": "category1",
                "downloaded": 100,
                "uploaded": 100,
            },
            {
                "name": "Torrent 2",
                "size": 200,
                "category": "category2",
                "downloaded": 200,
                "uploaded": 200,
            },
            {
                "name": "Torrent 3",
                "size": 300,
                "category": "category3",
                "downloaded": 300,
                "uploaded": 300,
            },
        ]
        # Mock the client.torrent_categories.categories attribute
        self.collector.client.torrent_categories.categories = {
            "category1": {"name": "Category 1"},
            "category2": {"name": "Category 2"},
            "category3": {"name": "Category 3"},
        }

        result = self.collector._get_qbittorrent_by_torrent_metric_gauges()

        torrent_size_metric = result[0]
        self.assertIsInstance(torrent_size_metric, GaugeMetricFamily)
        self.assertEqual(torrent_size_metric.name, "qbittorrent_torrent_size")
        self.assertEqual(torrent_size_metric.documentation, "Size of the torrent")
        self.assertEqual(
            torrent_size_metric.samples[0].labels,
            {
                "name": "Torrent 1",
                "category": "category1",
                "server": "localhost:8080/qbt/",
            },
        )
        self.assertEqual(torrent_size_metric.samples[0].value, 100)

        torrent_downloaded_metric = result[1]
        self.assertIsInstance(torrent_downloaded_metric, GaugeMetricFamily)
        self.assertEqual(
            torrent_downloaded_metric.name, "qbittorrent_torrent_downloaded"
        )
        self.assertEqual(
            torrent_downloaded_metric.documentation, "Downloaded data for the torrent"
        )
        self.assertEqual(
            torrent_downloaded_metric.samples[0].labels,
            {
                "name": "Torrent 1",
                "category": "category1",
                "server": "localhost:8080/qbt/",
            },
        )
        self.assertEqual(torrent_downloaded_metric.samples[0].value, 100)

        torrent_uploaded_metric = result[2]
        self.assertIsInstance(torrent_uploaded_metric, GaugeMetricFamily)
        self.assertEqual(torrent_uploaded_metric.name, "qbittorrent_torrent_uploaded")
        self.assertEqual(
            torrent_uploaded_metric.documentation, "Uploaded data for the torrent"
        )
        self.assertEqual(
            torrent_uploaded_metric.samples[0].labels,
            {
                "name": "Torrent 1",
                "category": "category1",
                "server": "localhost:8080/qbt/",
            },
        )
        self.assertEqual(torrent_uploaded_metric.samples[0].value, 100)

    def test_collect_torrent_tags_metric_gauge(self):
        result = self.collector._get_qbittorrent_torrent_tags_metrics_gauge()

        self.assertIsInstance(result, GaugeMetricFamily)
        self.assertEqual(result.name, "qbittorrent_torrents_count")
        self.assertEqual(result.documentation, "Number of torrents")
        self.assertEqual(
            result.samples[0].labels,
            {
                "status": "error",
                "category": "Uncategorized",
                "server": "localhost:8080/qbt/",
            },
        )
        self.assertEqual(result.samples[0].value, 0)

    def test_collect(self):
        metrics = list(self.collector.collect())
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
                name="qbittorrent_total_peer_connections",
                value=0,
                labels={"server": "localhost:8080/qbt/"},
                help_text="Total number of peer connections.",
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
        self.assertEqual(
            collector.connection_string,
            "http://qbittorrent.example.com:8081/qbittorrent/",
        )

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
        self.assertEqual(
            collector.connection_string, "https://qbittorrent2.example.com:8084"
        )

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
        self.assertEqual(
            collector.connection_string, "https://qbittorrent3.example.com:443/server/"
        )

        config = {
            "host": "qbittorrent4.example.com",
            "port": "443",
            "ssl": True,
            "url_base": "server/",
            "username": "user",
            "password": "pass",
            "verify_webui_certificate": True,
            "metrics_prefix": "qbittorrent",
        }
        collector = QbittorrentMetricsCollector(config)
        self.assertEqual(collector.server, "qbittorrent4.example.com:443/server/")
        self.assertEqual(
            collector.connection_string, "https://qbittorrent4.example.com:443/server/"
        )
