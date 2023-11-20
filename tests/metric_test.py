import unittest

from qbittorrent_exporter.exporter import Metric, MetricType


class TestMetric(unittest.TestCase):
    def test_metric_initialization(self):
        metric = Metric(name="test_metric", value=10)
        self.assertEqual(metric.name, "test_metric")
        self.assertEqual(metric.value, 10)
        self.assertEqual(metric.labels, {})
        self.assertEqual(metric.help_text, "")
        self.assertEqual(metric.metric_type, MetricType.GAUGE)
