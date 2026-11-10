#!/bin/bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p llvm-project && pushd llvm-project

git init

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin git@github.com:llvm/llvm-project.git
  # git remote add origin https://gitcode.com/GitHub_Trending/ll/llvm-project.git
  # git remote add origin /repo/llvm-project
fi

######

git sparse-checkout set --no-cone \
  /cmake /llvm /mlir /lld /libunwind /libc /clang \
  '!/llvm/test' '!/llvm/unittests' '!/llvm/docs' \
  '!/mlir/test' '!/mlir/unittests' '!/mlir/docs' \
  '!/lld/test' \
  '/third-party/siphash' \
  /.vscode '/*.*' '!/.ci' '!/.github'

git sparse-checkout add \
  '!/llvm/utils/gn' \
  '!/llvm/lib/Target' '/llvm/lib/Target/*.*' \
  '/llvm/lib/Target/RISCV' '/llvm/lib/Target/ARM' '/llvm/lib/Target/AArch64' \
  '/llvm/lib/Target/AMDGPU' '/llvm/lib/Target/NVPTX' '/llvm/lib/Target/X86' \
  '/llvm/lib/Target/SPIRV' '/llvm/lib/Target/PowerPC'

git sparse-checkout add \
  '/llvm/docs' '/mlir/test' '/mlir/docs'

git sparse-checkout list

######

# release/23.x, resolved from the upstream branch on 2026-11-10.
LLVM_SHA="c47d7823685a0e7048795e0cd2d58ad35e454ee9"

if ! git cat-file -e "$LLVM_SHA^{commit}" 2>/dev/null; then
  git fetch --depth 1 origin "$LLVM_SHA"
fi
# git checkout -b sync $LLVM_SHA
git checkout "$LLVM_SHA"

popd

###############################################################################
