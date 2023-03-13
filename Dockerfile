FROM alpine:3.11

# Installing required packages
RUN apk add --update --no-cache \
    python3

# Install package
WORKDIR /code
COPY . .
RUN pip3 install .

ENV IMMICH_API_TOKEN="PEsZWYz5Yf5FhxYQpEMebFFkxwpEHvSiTbc2YMjLk"
ENV QBITTORRENT_HOST="http://192.168.178.2"
ENV QBITTORRENT_PORT="2283"
ENV QBITTORRENT_USER=""
ENV QBITTORRENT_PASS=""
ENV EXPORTER_PORT="8000"
ENV EXPORTER_LOG_LEVEL="INFO"

ENTRYPOINT ["qbittorrent-exporter"]
