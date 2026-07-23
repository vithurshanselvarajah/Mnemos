ARG BASE_IMAGE=python:3.14-slim
ARG INSTALL_PROVIDER=cpu

FROM ${BASE_IMAGE} AS base

ARG INSTALL_PROVIDER

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt /srv/requirements.txt
RUN python -m pip install --upgrade "pip>=25" \
    && python -m pip install --prefer-binary -r /srv/requirements.txt

COPY variants/${INSTALL_PROVIDER}/requirements.txt /srv/variant-requirements.txt
RUN if [ -s /srv/variant-requirements.txt ]; then \
        python -m pip install --prefer-binary -r /srv/variant-requirements.txt ; \
    fi

COPY app /srv/app
COPY variants /srv/variants

ENV MNEMOS_PROVIDER=${INSTALL_PROVIDER}

RUN mkdir -p /data/crops /srv/models

ARG RKNN_TOOLKIT_VERSION=v2.3.0
ARG RKNN_RT_SHA256=73993ed4b440460825f21611731564503cc1d5a0c123746477da6cd574f34885
RUN if [ "${INSTALL_PROVIDER}" = "rockchip" ]; then \
        curl -fsSL -o /usr/lib/librknnrt.so \
          "https://github.com/airockchip/rknn-toolkit2/raw/refs/tags/${RKNN_TOOLKIT_VERSION}/rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so" \
        && echo "${RKNN_RT_SHA256}  /usr/lib/librknnrt.so" | sha256sum -c - \
        && chmod 644 /usr/lib/librknnrt.so ; \
    fi

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
