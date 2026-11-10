#!/bin/bash

set -euo pipefail

ln -sfn "$PWD/scripts/CMakePresets.json" "$PWD/llvm-project/llvm/CMakeUserPresets.json"

pushd llvm-project

cmake --preset osx -S$PWD/llvm -B$PWD/build

# TODO: reduce cmake targets, only llvm & mlir libs

cmake --build $PWD/build --target all
# cmake --build $PWD/build --target install

popd

###############################################################################
