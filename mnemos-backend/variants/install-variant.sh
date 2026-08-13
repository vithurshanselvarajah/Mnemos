#!/usr/bin/env bash
set -euo pipefail

reqs=${1:?usage: install-variant.sh <requirements.txt>}
override_pkg=${PROVIDER_OVERRIDE_PKG:-onnxruntime-gpu}
override_block="${override_pkg%\-gpu}"

grep -vE "^${override_block}|^${override_pkg}" "${reqs}" \
    | grep -vE '^[[:space:]]*$|^#' \
    | xargs -r python -m pip install --prefer-binary

python -m pip install --prefer-binary --upgrade "${override_pkg}"
