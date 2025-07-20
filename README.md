# Prometheus qBittorrent exporter

<p align="center">
<img src="https://raw.githubusercontent.com/esanchezm/prometheus-qbittorrent-exporter/master/logo.png" height="230">
</p>

A prometheus exporter for qBittorrent. Get metrics from a server and offers them in a prometheus format.

![](https://img.shields.io/github/license/esanchezm/prometheus-qbittorrent-exporter?style=for-the-badge) ![](https://img.shields.io/maintenance/yes/2024?style=for-the-badge) ![](https://img.shields.io/docker/pulls/esanchezm/prometheus-qbittorrent-exporter?style=for-the-badge) ![](https://img.shields.io/github/forks/esanchezm/prometheus-qbittorrent-exporter?style=for-the-badge) ![](https://img.shields.io/github/stars/esanchezm/prometheus-qbittorrent-exporter?style=for-the-badge) ![](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/esanchezm/prometheus-qbittorrent-exporter/master/pyproject.toml&style=for-the-badge) [![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/esanchezm/prometheus-qbittorrent-exporter/python-coverage-comment-action-data/endpoint.json&label=tests%20coverage&style=for-the-badge)](https://htmlpreview.github.io/?https://github.com/esanchezm/prometheus-qbittorrent-exporter/blob/python-coverage-comment-action-data/htmlcov/index.html)

## How to use it

You can install this exporter with the following command:

```bash
pip3 install prometheus-qbittorrent-exporter
```

Then you can run it with

```
qbittorrent-exporter
```

Another option is run it in a docker container.

```
docker run \
    -e QBITTORRENT_PORT=8080 \
    -e QBITTORRENT_HOST=myserver.local \
    -p 8000:8000 \
    ghcr.io/esanchezm/prometheus-qbittorrent-exporter
```
Add this to your prometheus.yml
```
  - job_name: "qbittorrent_exporter"
    static_configs:
        - targets: ['yourqbittorrentexporter:port']
```
The application reads configuration using environment variables:

| Environment variable       | Default       | Description |
| -------------------------- | ------------- | ----------- |
| `QBITTORRENT_HOST`         |               | qbittorrent server hostname |
| `QBITTORRENT_PORT`         |               | qbittorrent server port |
| `QBITTORRENT_SSL`          | `False`       | Whether to use SSL to connect or not. Will be forced to `True` when using port 443  |
| `QBITTORRENT_URL_BASE`     | `""`          | qbittorrent server path or base URL |
| `QBITTORRENT_USER`         | `""`          | qbittorrent username |
| `QBITTORRENT_PASS`         | `""`          | qbittorrent password |
| `EXPORTER_ADDRESS`         | `0.0.0.0`     | Exporter listening IP address |
| `EXPORTER_PORT`            | `8000`        | Exporter listening port |
| `EXPORTER_LOG_LEVEL`       | `INFO`        | Log level. One of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `METRICS_PREFIX`           | `qbittorrent` | Prefix to add to all the metrics |
| `VERIFY_WEBUI_CERTIFICATE` | `True`        | Whether to verify SSL certificate when connecting to the qbittorrent server. Any other value but `True` will disable the verification |


## Metrics

These are the metrics this program exports, assuming the `METRICS_PREFIX` is `qbittorrent`:


| Metric name                                         | Type     | Description      |
| --------------------------------------------------- | -------- | ---------------- |
| `qbittorrent_up`                                    | gauge    | Whether the qBittorrent server is answering requests from this exporter. A `version` label with the server version is added. |
| `qbittorrent_connected`                                         | gauge    | Whether the qBittorrent server is connected to the Bittorrent network.  |
| `qbittorrent_firewalled`                                        | gauge    | Whether the qBittorrent server is connected to the Bittorrent network but is behind a firewall.  |
| `qbittorrent_dht_nodes`                                         | gauge    | Number of DHT nodes connected to. |
| `qbittorrent_dl_info_data`                                      | counter  | Data downloaded since the server started, in bytes. |
| `qbittorrent_up_info_data`                                      | counter  | Data uploaded since the server started, in bytes. |
| `qbittorrent_alltime_dl_total`                                  | counter  | Total historical data downloaded, in bytes. |
| `qbittorrent_alltime_ul_total`                                  | counter  | Total historical data uploaded, in bytes. |
| `qbittorrent_torrents_count`                                    | gauge    | Number of torrents for each `category` and `status`. Example: `qbittorrent_torrents_count{category="movies",status="downloading"}`|

## Screenshot

![](./grafana/screenshot.png)

[More info](./grafana/README.md)

## License

This software is released under the [GPLv3 license](LICENSE).
