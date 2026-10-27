ARG PYTHON_BASE=3.15-alpine@sha256:0aa144e9ec2ae8fd80dfd94070ef3e432a0df17b6e5e0091dc05323974ce9913
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
