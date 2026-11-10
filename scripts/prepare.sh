#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
for tool in uv cmake ninja clang clang++; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
if [[ ! -f llvm-project/mlir/python/requirements.txt ]]; then
  bash scripts/llvm_download.sh
fi
if [[ ! -x .venv/bin/python ]]; then
  uv venv --python 3.14 .venv
fi
.venv/bin/python -c 'import sys, sysconfig; assert sys.version_info >= (3, 12) and not sysconfig.get_config_var("Py_GIL_DISABLED"), "abi3 requires CPython 3.12+ with the GIL"'
uv pip install --python .venv/bin/python -r llvm-project/mlir/python/requirements.txt
