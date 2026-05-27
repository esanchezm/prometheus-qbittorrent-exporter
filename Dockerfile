ARG PYTHON_BASE=3.14-alpine@sha256:5a824eb82cc75361f98611f3cfc5091ea33f10a6ccea4d4ebdabbc523b9a1614
FROM python:$PYTHON_BASE AS builder

RUN apk add --no-cache gcc musl-dev && pip install -U pdm
ENV PDM_CHECK_UPDATE=false
COPY pyproject.toml pdm.lock README.md /project/
COPY qbittorrent_exporter/ /project/qbittorrent_exporter

WORKDIR /project
RUN pdm install --check --prod --no-editable

FROM python:$PYTHON_BASE

COPY --from=builder /project/.venv/ /project/.venv
ENV PATH="/project/.venv/bin:$PATH"

ENV QBITTORRENT_HOST=""
ENV QBITTORRENT_PORT=""
ENV QBITTORRENT_USER=""
ENV QBITTORRENT_PASS=""
ENV QBITTORRENT_API_KEY=""
ENV EXPORTER_PORT="8000"
ENV EXPORTER_LOG_LEVEL="INFO"

ENTRYPOINT ["qbittorrent-exporter"]
