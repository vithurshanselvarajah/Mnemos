ARG BASE_IMAGE=python:3.14-slim
ARG INSTALL_PROVIDER=cpu


FROM ${BASE_IMAGE} AS python-base

ARG INSTALL_PROVIDER
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive


FROM python-base AS cpu-base



FROM python-base AS rockchip-base

ARG TARGETARCH
ARG RKNN_TOOLKIT_VERSION=v2.3.0
ARG RKNN_RT_SHA256=73993ed4b440460825f21611731564503cc1d5a0c123746477da6cd574f34885

RUN if [ "${TARGETARCH}" != "arm64" ]; then \
        echo "ERROR: Rockchip provider requires linux/arm64 (TARGETARCH=${TARGETARCH})" >&2; \
        exit 1; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /usr/lib/librknnrt.so \
        "https://github.com/airockchip/rknn-toolkit2/raw/refs/tags/${RKNN_TOOLKIT_VERSION}/rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so" \
    && echo "${RKNN_RT_SHA256}  /usr/lib/librknnrt.so" | sha256sum -c - \
    && chmod 644 /usr/lib/librknnrt.so \
    && ldconfig



FROM nvidia/cuda:13.3.1-cudnn-runtime-ubuntu26.04 AS nvidia-base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.14 \
        python3.14-venv \
        python3-pip \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        curl \
        ca-certificates \
        sqlite3 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN python3.14 -m venv /opt/venv

ENV PATH=/opt/venv/bin:${PATH} \
    CUDA_HOME=/usr/local/cuda

RUN python --version \
    && python -c 'import sys; assert sys.version_info[:2] == (3, 14), sys.version' \
    && python -c 'import sys; print("Python:", sys.executable)' \
    && ldconfig -p | grep -q 'libcudnn.so.9' \
    && ldconfig -p | grep -q 'libcudart.so.13'



FROM ${INSTALL_PROVIDER}-base AS base

ARG INSTALL_PROVIDER

ENV MNEMOS_PROVIDER=${INSTALL_PROVIDER}



RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        curl \
        ca-certificates \
        sqlite3 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*



WORKDIR /srv

COPY requirements.txt /srv/requirements.txt

RUN python -m pip install --upgrade "pip>=25" \
    && python -m pip install --prefer-binary \
        -r /srv/requirements.txt



COPY variants/install-variant.sh /usr/local/bin/mnemos-install-variant

RUN chmod +x /usr/local/bin/mnemos-install-variant

COPY variants/${INSTALL_PROVIDER}/requirements.txt \
    /srv/variant-requirements.txt

RUN if [ "${INSTALL_PROVIDER}" = "nvidia" ]; then \
        mnemos-install-variant /srv/variant-requirements.txt; \
    elif [ -s /srv/variant-requirements.txt ]; then \
        python -m pip install --prefer-binary \
            -r /srv/variant-requirements.txt; \
    fi



COPY app /srv/app
COPY variants /srv/variants



RUN mkdir -p \
        /data/crops \
        /data/backups \
        /srv/models



RUN if [ "${INSTALL_PROVIDER}" = "nvidia" ]; then \
        echo "=== NVIDIA runtime ===" \
        && python --version \
        && echo "CUDA:" \
        && ls -ld /usr/local/cuda \
        && echo "cuDNN:" \
        && ldconfig -p | grep libcudnn.so.9 \
        && echo "CUDA runtime libraries:" \
        && ldconfig -p | grep -E 'libcudart.so.13|libcublas.so.13'; \
    elif [ "${INSTALL_PROVIDER}" = "rockchip" ]; then \
        echo "=== Rockchip runtime ===" \
        && python --version \
        && ls -lh /usr/lib/librknnrt.so \
        && ldconfig -p | grep librknnrt; \
    else \
        echo "=== CPU runtime ===" \
        && python --version; \
    fi



EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]