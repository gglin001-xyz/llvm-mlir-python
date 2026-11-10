#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
bash scripts/prepare.sh
ln -sfn "$PWD/scripts/CMakePresets.json" llvm-project/llvm/CMakeUserPresets.json
cmake --preset "${LLVM_PRESET:-python}" -S llvm-project/llvm -B llvm-project/build "$@"
mapfile -t targets < <(.venv/bin/python -c 'import json; p = json.load(open("scripts/wheel_contents.json")); print(*p["tools"], *p["runtimes"], sep="\n")')
cmake --build llvm-project/build --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-64}" \
  --target MLIRPythonModules "${targets[@]}"
