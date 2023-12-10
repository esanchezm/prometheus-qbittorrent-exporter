FROM python:3.12-alpine

# Install package
WORKDIR /code
COPY pyproject.toml pdm.lock README.md ./
COPY qbittorrent_exporter ./qbittorrent_exporter
RUN pip install . \
    && rm -rf /root/.cache/pip

ENV QBITTORRENT_HOST=""
ENV QBITTORRENT_PORT=""
ENV QBITTORRENT_USER=""
ENV QBITTORRENT_PASS=""
ENV EXPORTER_PORT="8000"
ENV EXPORTER_LOG_LEVEL="INFO"

ENTRYPOINT ["qbittorrent-exporter"]
