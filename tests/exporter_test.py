import unittest
from unittest.mock import MagicMock, patch

from prometheus_client.metrics_core import CounterMetricFamily, GaugeMetricFamily

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
            "username": "user",
            "password": "pass",
            "verify_webui_certificate": False,
        }
        self.collector = QbittorrentMetricsCollector(self.config)

    def test_init(self):
        self.assertEqual(self.collector.config, self.config)
        self.mock_client.assert_called_once_with(
            host=self.config["host"],
            port=self.config["port"],
            username=self.config["username"],
            password=self.config["password"],
            VERIFY_WEBUI_CERTIFICATE=self.config["verify_webui_certificate"],
        )

    def test_collect_gauge(self):
        mock_metric = Metric(
            name="test_gauge",
            metric_type=MetricType.GAUGE,
            help_text="Test Gauge",
            labels={"label1": "value1"},
            value=10,
        )
        self.collector.get_qbittorrent_metrics = MagicMock(return_value=[mock_metric])

        result = next(self.collector.collect())

        self.assertIsInstance(result, GaugeMetricFamily)
        self.assertEqual(result.name, "test_gauge")
        self.assertEqual(result.documentation, "Test Gauge")
        self.assertEqual(result.samples[0].labels, {"label1": "value1"})
        self.assertEqual(result.samples[0].value, 10)

    def test_collect_counter(self):
        mock_metric = Metric(
            name="test_counter",
            metric_type=MetricType.COUNTER,
            help_text="Test Counter",
            labels={"label2": "value2"},
            value=230,
        )
        self.collector.get_qbittorrent_metrics = MagicMock(return_value=[mock_metric])

        result = next(self.collector.collect())

        self.assertIsInstance(result, CounterMetricFamily)
        self.assertEqual(result.name, "test_counter")
        self.assertEqual(result.documentation, "Test Counter")
        self.assertEqual(result.samples[0].labels, {"label2": "value2"})
        self.assertEqual(result.samples[0].value, 230)
