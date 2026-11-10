"""Verify the installed MLIR wheel, including native execution."""

import ctypes
import sys
from importlib.metadata import distribution
from pathlib import Path

import numpy as np
from mlir import ir
from mlir.dialects import arith, func
from mlir.execution_engine import ExecutionEngine
from mlir.passmanager import PassManager


def main():
    installed = distribution("mlir-python-bindings").locate_file("mlir")
    assert Path(ir.__file__).resolve().is_relative_to(installed.resolve()), ir.__file__
    with ir.Context(), ir.Location.unknown():
        values = np.array([[1, 2], [3, 4]], dtype=np.int32)
        attribute = ir.DenseElementsAttr.get(values)
        np.testing.assert_array_equal(np.asarray(attribute), values)

        module = ir.Module.create()
        with ir.InsertionPoint(module.body):
            i32 = ir.IntegerType.get_signless(32)

            @func.FuncOp.from_py_func(i32, i32)
            def add(lhs, rhs):
                return arith.addi(lhs, rhs)

            add.func_op.attributes["llvm.emit_c_interface"] = ir.UnitAttr.get()

        # Exercise parsing as well as the Python operation builders.
        module = ir.Module.parse(str(module))
        assert module.operation.verify()
        PassManager.parse("builtin.module(canonicalize)").run(module.operation)
        PassManager.parse(
            "builtin.module(convert-arith-to-llvm,convert-func-to-llvm,"
            "reconcile-unrealized-casts)"
        ).run(module.operation)
        assert module.operation.verify()

        engine = ExecutionEngine(module, opt_level=2)
        lhs, rhs, result = ctypes.c_int32(20), ctypes.c_int32(22), ctypes.c_int32()
        engine.invoke(
            "add", ctypes.byref(lhs), ctypes.byref(rhs), ctypes.byref(result)
        )
        assert result.value == 42, result.value

    print(f"Python {sys.version.split()[0]}: {ir.__file__}")
    print("PASS: IR builders/parser, NumPy roundtrip, passes, and JIT (20 + 22 = 42)")


if __name__ == "__main__":
    main()
