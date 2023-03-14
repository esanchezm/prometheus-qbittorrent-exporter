FROM alpine:3.11

# Installing required packages
RUN apk add --update --no-cache \
    python3

# Install package
WORKDIR /code
COPY . .
RUN pip3 install .

ENV IMMICH_API_TOKEN=""
ENV IMMICH_HOST=""
ENV IMMICH_PORT=""
ENV QBITTORRENT_HOST=""
ENV QBITTORRENT_PORT=""
ENV QBITTORRENT_USER=""
ENV QBITTORRENT_PASS=""
#has to be EXPORT_PORT 8000 or else it does not work, same applies to the env file
ENV EXPORTER_PORT="8000"
ENV EXPORTER_LOG_LEVEL="INFO"

ENTRYPOINT ["qbittorrent-exporter"]
