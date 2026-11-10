#!/usr/bin/env bash
set -euo pipefail

LLVM_PRESET=python-lld exec bash "$(dirname "${BASH_SOURCE[0]}")/llvm_build.sh" "$@"
