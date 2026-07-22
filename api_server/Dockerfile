FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt


FROM python:3.11-slim AS runtime

ARG APP_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="SupportHR Backend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --no-create-home app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 data ./data

USER 10001:10001

EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
