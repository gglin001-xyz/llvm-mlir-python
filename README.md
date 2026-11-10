# MLIR Python bindings

Build with uv + Python 3.14, using the CPython 3.12+ stable ABI (abi3).
Requires Git, uv, CMake >= 3.29, Ninja, Clang/Clang++ and mold.

Run from the repository root:

```bash
# Build
bash scripts/llvm_build.sh
uv run scripts/build_wheel.py

# Install and verify
uv pip install --python .venv/bin/python dist/*.whl
.venv/bin/python -I scripts/check_python.py
```
