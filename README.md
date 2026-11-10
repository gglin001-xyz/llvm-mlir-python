# MLIR Python bindings

Build with uv + Python 3.14, using the CPython 3.12+ stable ABI (abi3).
Requires Git, uv, CMake >= 3.29, Ninja, Clang/Clang++ and mold.
Clang uses the system GCC development files under `/usr`.
The current wheel targets Linux x86_64 with glibc >= 2.35.
Includes Native, NVPTX, AMDGPU and RISCV backends, JIT runtime libraries,
LLVM/MLIR headers, and six MLIR tools (listed in `scripts/wheel_contents.json`).
Tools are available on the environment's `PATH` after activation.
GPU device execution still requires the corresponding SDK/runtime.

Run from the repository root:

```bash
# Build
bash scripts/llvm_build.sh
uv run scripts/build_wheel.py

# Install and verify
uv pip install --python .venv/bin/python --reinstall-package mlir-python-bindings dist/*.whl
.venv/bin/python -I scripts/check_python.py
```
