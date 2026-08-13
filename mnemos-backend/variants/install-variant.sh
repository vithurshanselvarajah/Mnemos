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
# Anything matching this token is skipped in the bulk pass so a transitive
# pull cannot win the on-disk race against the GPU override package.
override_block="${override_pkg%\-gpu}"

# Bulk-install every package except the override family, WITH their normal
# transitive deps (so e.g. insightface pulls in onnx, tqdm, Pillow, etc.).
# Earlier this script also stripped --no-deps, which suppressed those
# transitive deps and caused modules like "onnx" to be missing at runtime.
grep -vE "^${override_block}|^${override_pkg}" "${reqs}" \
    | grep -vE '^[[:space:]]*$|^#' \
    | xargs -r python -m pip install --prefer-binary

# Override package last, with its own deps, so it wins the on-disk race.
python -m pip install --prefer-binary --upgrade "${override_pkg}"
