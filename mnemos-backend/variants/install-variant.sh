#!/usr/bin/env bash
# Variant installer for providers whose onnxruntime pull is shadowed by a
# transitive dependency on plain `onnxruntime` (e.g. insightface on nvidia).
#
# Algorithm: install every line of the requirements file except the
# GPU/override package with --no-deps, then install the override package last
# with its own deps so it wins the on-disk race against any plain `onnxruntime`
# pulled transitively.
set -euo pipefail

reqs=${1:?usage: install-variant.sh <requirements.txt>}
override_pkg=${PROVIDER_OVERRIDE_PKG:-onnxruntime-gpu}

grep -v "^${override_pkg}" "${reqs}" \
    | grep -vE '^[[:space:]]*$|^#' \
    | xargs -r python -m pip install --prefer-binary --no-deps

python -m pip install --prefer-binary "${override_pkg}"
