import os
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from prometheus_client.metrics_core import GaugeMetricFamily
from qbittorrentapi import Client, TorrentStates
from requests import Response
from requests.exceptions import Timeout

from qbittorrent_exporter.exporter import (
    Metric,
    MetricType,
    QbittorrentMetricsCollector,
    ShutdownSignalHandler,
    _parse_bool,
    _validate_log_level,
    get_config,
)


class TestQbittorrentMetricsCollector(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("qbittorrent_exporter.exporter.Client")
        self.mock_client = self.patcher.start()
        self.config = {
            "host": "localhost",
            "port": "8080",
            "ssl": False,
            "url_base": "qbt/",
            "username": "user",
            "password": "pass",
            "api_key": "",
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
        # Create a client for tests that call metric helpers directly.
        self.client = self.collector._create_client()

    def tearDown(self):
        self.patcher.stop()

    def test_init(self):
        self.assertEqual(self.collector.config, self.config)
        # Client must not be instantiated during __init__; verify with a fresh collector.
        self.mock_client.reset_mock()
        QbittorrentMetricsCollector(self.config)
        self.mock_client.assert_not_called()

    def test_create_client(self):
        self.mock_client.reset_mock()
        self.collector._create_client()
        self.mock_client.assert_called_once_with(
            host=f"http://{self.config['host']}:{self.config['port']}/qbt/",
            username=self.config["username"],
            password=self.config["password"],
            VERIFY_WEBUI_CERTIFICATE=self.config["verify_webui_certificate"],
        )

    @staticmethod
    def _api_response(method, url, **kwargs):
        response = Response()
        response.status_code = 200
        response.url = url
        if url.endswith("/app/version"):
            response._content = b"5.2.2"
        elif url.endswith("/app/webapiVersion"):
            response._content = b"2.15.0"
        elif url.endswith("/sync/maindata"):
            response._content = b'{"server_state":{"connection_status":"connected"}}'
        elif url.endswith("/torrents/info"):
            response._content = b"[]"
        else:
            response._content = b"{}"
        return response

    def test_cleanup_timeout_does_not_shorten_metric_requests(self):
        self.mock_client.side_effect = Client

        with patch(
            "requests.sessions.Session.request", side_effect=self._api_response
        ) as request:
            metrics = list(self.collector.collect())

        self.assertTrue(metrics[0].samples[0].value)
        cleanup_requests = request.call_args_list[-1:]
        self.assertEqual(
            [c.args[1].rsplit("/", 2)[-2:] for c in cleanup_requests],
            [["auth", "logout"]],
        )
        for call in cleanup_requests:
            self.assertEqual(call.kwargs["timeout"], 5)

        metric_requests = request.call_args_list[:-1]
        self.assertTrue(
            any(c.args[1].endswith("/sync/maindata") for c in metric_requests)
        )
        self.assertTrue(
            any(c.args[1].endswith("/torrents/info") for c in metric_requests)
        )
        for call in metric_requests:
            self.assertEqual(call.kwargs["timeout"], 15.1)

    def test_logout_is_sent_after_exhausted_preflight_timeouts(self):
        self.mock_client.side_effect = Client
        client = self.collector._create_client()
        self.mock_client.side_effect = None
        self.mock_client.return_value = client

        def fail_preflight(method, url, **kwargs):
            if url.endswith("/app/version"):
                raise Timeout("Session check timed out")
            return self._api_response(method, url, **kwargs)

        with patch(
            "requests.sessions.Session.request", side_effect=self._api_response
        ) as request:
            scrape = self.collector.collect()
            try:
                # Fetch every metric, leaving the generator suspended before cleanup.
                metrics = []
                for metric in scrape:
                    metrics.append(metric)
                    if metric.name == "qbittorrent_torrents_count":
                        break
                self.assertTrue(metrics[0].samples[0].value)
                self.assertTrue(
                    any(
                        c.args[1].endswith("/torrents/info")
                        for c in request.call_args_list
                    )
                )

                request.reset_mock()
                request.side_effect = fail_preflight
                self.assertFalse(client.is_logged_in)
                preflight_requests = [
                    c
                    for c in request.call_args_list
                    if c.args[1].endswith("/app/version")
                ]
                self.assertEqual(len(preflight_requests), 2)
            finally:
                scrape.close()

        self.assertEqual(
            [
                c.args[1].rsplit("/", 2)[-2:]
                for c in request.call_args_list
                if c.args[0] == "post"
            ],
            [["app", "version"], ["app", "version"], ["auth", "logout"]],
        )
        self.assertEqual(request.call_args.kwargs["timeout"], 5)

    def test_collect_recreates_client(self):
        """Each call to collect() must create a fresh Client so that
        stale internal state (e.g. the HTTP fallback triggered by qbittorrentapi after
        an SSL failure) does not persist across scrapes."""
        self.mock_client.reset_mock()
        list(self.collector.collect())
        list(self.collector.collect())
        self.assertEqual(self.mock_client.call_count, 2)

    def test_collect_releases_each_session(self):
        clients = [MagicMock(), MagicMock()]
        self.mock_client.side_effect = clients

        for client in clients:
            list(self.collector.collect())
            client._post.assert_called_once_with(
                _name="auth", _method="logout", requests_args={"timeout": 5}
            )

    def test_overlapping_scrapes_use_separate_clients(self):
        clients = [MagicMock(), MagicMock()]
        self.mock_client.side_effect = clients
        for index, client in enumerate(clients):
            client.sync_maindata.return_value = {
                "server_state": {"connection_status": "connected"}
            }
            client.app.version = f"5.2.{index}"
            client.torrent_categories.categories = {}
            client.torrents.info.return_value = [
                {
                    "name": f"Torrent {index}",
                    "size": index + 1,
                    "downloaded": index,
                    "category": "",
                    "state": TorrentStates.DOWNLOADING,
                }
            ]

        first = self.collector.collect()
        second = self.collector.collect()
        try:
            self.assertEqual(next(first).samples[0].labels["version"], "5.2.0")
            self.assertEqual(next(second).samples[0].labels["version"], "5.2.1")

            # Finish the first scrape while the second still owns an active session.
            first_metrics = list(first)
            clients[0]._post.assert_called_once_with(
                _name="auth", _method="logout", requests_args={"timeout": 5}
            )
            clients[1]._post.assert_not_called()
            second_metrics = list(second)

            for index, metrics in enumerate((first_metrics, second_metrics)):
                size = next(m for m in metrics if m.name == "qbittorrent_torrent_size")
                self.assertEqual(size.samples[0].labels["name"], f"Torrent {index}")
                self.assertEqual(size.samples[0].value, index + 1)
                clients[index].sync_maindata.assert_called_once_with()
                self.assertEqual(clients[index].torrents.info.call_count, 2)
                clients[index]._post.assert_called_once_with(
                    _name="auth", _method="logout", requests_args={"timeout": 5}
                )
        finally:
            first.close()
            second.close()

    def test_collect_releases_session_after_api_failure(self):
        self.client.sync_maindata.side_effect = Exception("Connection error")

        metrics = list(self.collector.collect())

        self.assertEqual(metrics[0].name, "qbittorrent_up")
        self.assertFalse(metrics[0].samples[0].value)
        self.client._post.assert_called_once_with(
            _name="auth", _method="logout", requests_args={"timeout": 5}
        )

    def test_collect_releases_session_on_unexpected_error(self):
        with (
            patch.object(
                self.collector,
                "_get_qbittorrent_by_torrent_metric_gauges",
                side_effect=ValueError("Invalid torrent data"),
            ),
            self.assertRaisesRegex(ValueError, "Invalid torrent data"),
        ):
            list(self.collector.collect())

        self.client._post.assert_called_once_with(
            _name="auth", _method="logout", requests_args={"timeout": 5}
        )

    def test_collect_releases_session_when_generator_closed(self):
        metrics = self.collector.collect()
        next(metrics)
        self.client._post.assert_not_called()

        metrics.close()

        self.client._post.assert_called_once_with(
            _name="auth", _method="logout", requests_args={"timeout": 5}
        )

    def test_collect_logout_timeout_does_not_fail_scrape(self):
        self.client._post.side_effect = Timeout("Logout timed out")

        with self.assertLogs(level="ERROR") as logs:
            metrics = list(self.collector.collect())

        self.assertTrue(metrics)
        self.assertIn(
            "Couldn't log out of qBittorrent: Logout timed out", logs.output[0]
        )

    def test_collect_with_api_key_does_not_log_out(self):
        self.config["api_key"] = "qbt_abcdefghijklmnopqrstuvwxyz12"

        list(self.collector.collect())

        self.client._post.assert_not_called()

    def test_create_client_with_api_key(self):
        self.mock_client.reset_mock()
        self.collector.config["api_key"] = "qbt_abcdefghijklmnopqrstuvwxyz12"

        self.collector._create_client()

        kwargs = self.mock_client.call_args.kwargs
        self.assertEqual(
            kwargs["host"], f"http://{self.config['host']}:{self.config['port']}/qbt/"
        )
        auth_header = kwargs["EXTRA_HEADERS"]["Authorization"]
        self.assertEqual(auth_header.split()[0], "Bearer")
        self.assertTrue(auth_header.endswith(self.collector.config["api_key"]))
        self.assertNotIn("username", kwargs)
        self.assertNotIn("password", kwargs)

    def test_collect_by_torrent_metric_gauges(self):
        # Mock the return value of self.client.torrents.info()
        self.client.torrents.info.return_value = [
            {
                "name": "Torrent 1",
                "size": 100,
                "category": "category1",
                "downloaded": 100,
            },
            {
                "name": "Torrent 2",
                "size": 200,
                "category": "category2",
                "downloaded": 200,
            },
            {
                "name": "Torrent 3",
                "size": 300,
                "category": "category3",
                "downloaded": 300,
            },
        ]
        # Mock the client.torrent_categories.categories attribute
        self.client.torrent_categories.categories = {
            "category1": {"name": "Category 1"},
            "category2": {"name": "Category 2"},
            "category3": {"name": "Category 3"},
        }

        result = self.collector._get_qbittorrent_by_torrent_metric_gauges(self.client)

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

    def test_collect_torrent_tags_metric_gauge(self):
        result = self.collector._get_qbittorrent_torrent_tags_metrics_gauge(self.client)

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
        self.client.torrent_categories.categories = {
            "category1": {"name": "Category 1"},
            "category2": {"name": "Category 2"},
            "category3": {"name": "Category 3"},
        }

        categories = self.collector._fetch_categories(self.client)
        self.assertIsInstance(categories, dict)
        self.assertNotEqual(len(categories), 0)
        self.assertEqual(categories["category1"]["name"], "Category 1")
        self.assertEqual(categories["category2"]["name"], "Category 2")
        self.assertEqual(categories["category3"]["name"], "Category 3")

    def test_fetch_categories_exception(self):
        type(self.client.torrent_categories).categories = PropertyMock(
            side_effect=Exception("Error fetching categories")
        )
        categories = self.collector._fetch_categories(self.client)
        self.assertEqual(categories, {})

    def test_fetch_torrents_success(self):
        # Mock the return value of self.client.torrents.info()
        self.client.torrents.info.return_value = [
            {"name": "Torrent 1", "size": 100},
            {"name": "Torrent 2", "size": 200},
            {"name": "Torrent 3", "size": 300},
        ]

        expected_result = [
            {"name": "Torrent 1", "size": 100},
            {"name": "Torrent 2", "size": 200},
            {"name": "Torrent 3", "size": 300},
        ]

        result = self.collector._fetch_torrents(self.client)
        self.assertEqual(result, expected_result)

    def test_fetch_torrents_exception(self):
        # Mock an exception being raised by self.client.torrents.info()
        self.client.torrents.info.side_effect = Exception("Connection error")

        expected_result = []

        result = self.collector._fetch_torrents(self.client)
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
        self.client.sync_maindata.return_value = {
            "server_state": {"connection_status": "connected"}
        }
        self.client.app.version = "1.2.3"

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

        metrics = self.collector._get_qbittorrent_status_metrics(self.client)
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

    def test_url_base_leading_slash(self):
        config = {**self.config, "url_base": "/qbt"}
        collector = QbittorrentMetricsCollector(config)
        self.assertEqual(collector.server, "localhost:8080/qbt")
        self.assertEqual(collector.connection_string, "http://localhost:8080/qbt")


class TestConfig(unittest.TestCase):
    def test_parse_bool(self):
        for value in ("True", "true", "1", "yes", " True "):
            self.assertTrue(_parse_bool(value), value)
        for value in ("False", "", "0", "no", "anything"):
            self.assertFalse(_parse_bool(value), value)

    @patch.dict(os.environ, {}, clear=True)
    def test_get_config_bool_defaults(self):
        config = get_config()
        self.assertFalse(config["ssl"])
        self.assertFalse(config["export_metrics_by_torrent"])
        self.assertTrue(config["verify_webui_certificate"])

    @patch.dict(os.environ, {"VERIFY_WEBUI_CERTIFICATE": "true"}, clear=True)
    def test_get_config_verify_certificate_lowercase(self):
        self.assertTrue(get_config()["verify_webui_certificate"])

    @patch.dict(os.environ, {"EXPORTER_PORT": "abc"}, clear=True)
    def test_get_config_invalid_exporter_port(self):
        with self.assertRaises(SystemExit):
            get_config()

    def test_get_config_out_of_range_exporter_port(self):
        for port in ("0", "-1", "65536"):
            with (
                self.subTest(port=port),
                patch.dict(os.environ, {"EXPORTER_PORT": port}, clear=True),
                self.assertRaises(SystemExit),
            ):
                get_config()

    def test_get_config_file_variant(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret_path = os.path.join(tmp_dir, "secret")
            with open(secret_path, "w") as secret_file:
                secret_file.write("  s3cret\n")

            with patch.dict(
                os.environ, {"FILE__QBITTORRENT_PASS": secret_path}, clear=True
            ):
                self.assertEqual(get_config()["password"], "s3cret")

            missing_path = os.path.join(tmp_dir, "missing")
            with (
                patch.dict(
                    os.environ, {"FILE__QBITTORRENT_PASS": missing_path}, clear=True
                ),
                self.assertRaises(SystemExit),
            ):
                get_config()

    def test_validate_log_level(self):
        self.assertEqual(_validate_log_level("INFO"), "INFO")
        self.assertEqual(_validate_log_level(" debug "), "DEBUG")
        with self.assertRaises(SystemExit):
            _validate_log_level("VERBOSE")


class TestShutdownSignalHandler(unittest.TestCase):
    @patch("qbittorrent_exporter.exporter.signal.signal")
    def test_second_signal_force_kills(self, mock_signal):
        handler = ShutdownSignalHandler()
        self.assertEqual(mock_signal.call_count, 2)
        self.assertFalse(handler.is_shutting_down())

        handler._on_signal_received(None, None)
        self.assertTrue(handler.is_shutting_down())

        with self.assertRaises(SystemExit):
            handler._on_signal_received(None, None)
