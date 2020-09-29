# Prometheus qBittorrent exporter

A prometheus exporter for qBitorrent. Get metrics from a server and offers them in a prometheus format.


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
docker run -e QBITTORRENT_PORT=8080 -e QBITTORRENT_HOST=myserver.local -p 8000:8000 esanchezm/prometheus-qbittorrent-exporter
```

The application reads configuration using environment variables:

| Environment variable | Default       | Description |
| -------------------- | ------------- | ----------- |
| `QBITTORRENT_HOST`   |               | qbittorrent server hostname |
| `QBITTORRENT_PORT`   |               | qbittorrent server port |
| `QBITTORRENT_USER`   | `""`          | qbittorrent username |
| `QBITTORRENT_PASS`   | `""`          | qbittorrent password |
| `EXPORTER_PORT`      | `8000`        | Exporter listening port |
| `EXPORTER_LOG_LEVEL` | `INFO`        | Log level. One of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |


## Metrics

These are the metrics this program exports:


| Metric name                                         | Type     | Description      |
| --------------------------------------------------- | -------- | ---------------- |
| `qbittorrent_up`                                    | gauge    | Whether if the qBittorrent server is answering requests from this exporter. A `version` label with the server version is added |
| `connected`                                         | gauge    | Whether if the qBittorrent server is connected to the Bittorrent network.  |
| `firewalled`                                        | gauge    | Whether if the qBittorrent server is connected to the Bittorrent network but is behind a firewall.  |
| `dht_nodes`                                         | gauge    | Number of DHT nodes connected to |
| `dl_info_data`                                      | counter  | Data downloaded since the server started, in bytes |
| `up_info_data`                                      | counter  | Data uploaded since the server started, in bytes |
| `torrents_count`                                    | gauge    | Number of torrents for each `category` and `status`. Example: `torrents_count{category="movies",status="downloading"}`|

## License

This software is released under the [GPLv3 license](LICENSE).
