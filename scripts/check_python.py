"""Verify the installed MLIR wheel, including native execution."""

import ctypes
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

import numpy as np
from mlir import ir
from mlir.dialects import arith, func, gpu, llvm
import mlir.dialects.gpu.passes
from mlir.execution_engine import ExecutionEngine
from mlir.passmanager import PassManager
from mlir.runtime import get_ranked_memref_descriptor


def check_core():
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


def check_linalg():
    with ir.Context():
        module = ir.Module.parse("""
            module {
              func.func @matmul(%a: memref<2x3xf32>, %b: memref<3x4xf32>,
                               %out: memref<2x4xf32>) attributes {llvm.emit_c_interface} {
                %at = bufferization.to_tensor %a restrict : memref<2x3xf32> to tensor<2x3xf32>
                %bt = bufferization.to_tensor %b restrict : memref<3x4xf32> to tensor<3x4xf32>
                %empty = tensor.empty() : tensor<2x4xf32>
                %zero = arith.constant 0.0 : f32
                %init = linalg.fill ins(%zero : f32)
                    outs(%empty : tensor<2x4xf32>) -> tensor<2x4xf32>
                %result = linalg.matmul ins(%at, %bt : tensor<2x3xf32>, tensor<3x4xf32>)
                    outs(%init : tensor<2x4xf32>) -> tensor<2x4xf32>
                bufferization.materialize_in_destination %result in restrict writable %out
                    : (tensor<2x4xf32>, memref<2x4xf32>) -> ()
                return
              }
            }
        """)
        PassManager.parse(
            "builtin.module(eliminate-empty-tensors,empty-tensor-to-alloc-tensor,"
            "one-shot-bufferize{bufferize-function-boundaries},canonicalize,cse,"
            "func.func(convert-linalg-to-loops),lower-affine,convert-scf-to-cf,"
            "convert-math-to-llvm,convert-arith-to-llvm,expand-strided-metadata,"
            "finalize-memref-to-llvm,convert-func-to-llvm,convert-cf-to-llvm,"
            "reconcile-unrealized-casts)"
        ).run(module.operation)
        assert module.operation.verify()
        assert "define void @matmul" in llvm.translate_module_to_llvmir(module.operation)
        a = np.arange(6, dtype=np.float32).reshape(2, 3)
        b = np.arange(12, dtype=np.float32).reshape(3, 4)
        result = np.zeros((2, 4), dtype=np.float32)
        args = [ctypes.pointer(ctypes.pointer(get_ranked_memref_descriptor(array)))
                for array in (a, b, result)]
        engine = ExecutionEngine(module, opt_level=2)
        engine.invoke("matmul", *args)
        np.testing.assert_allclose(result, a @ b)


def check_gpu_codegen():
    for target, chip, expected in (("nvvm", "sm_70", b".entry"),
                                   ("rocdl", "gfx90a", b"s_endpgm")):
        with ir.Context():
            module = ir.Module.parse(f"""
                module attributes {{gpu.container_module}} {{
                  gpu.module @kernels [#{target}.target<chip = "{chip}">] {{
                    llvm.func @kernel() attributes {{{target}.kernel}} {{ llvm.return }}
                  }}
                }}
            """)
            PassManager.parse("builtin.module(gpu-module-to-binary{format=isa})").run(module.operation)
            assembly = gpu.ObjectAttr(module.body.operations[0].objects[0]).object
            assert expected in assembly, assembly


def check_tools(installed):
    def run(name, *args, source=None):
        return subprocess.run([str(installed / "bin" / name), *args], input=source,
                              text=True, capture_output=True, check=True).stdout

    optimized = run("mlir-opt", "--pass-pipeline=builtin.module(canonicalize)",
                    source="module { llvm.func @answer() -> i32 { "
                           "%c = llvm.mlir.constant(42 : i32) : i32 llvm.return %c : i32 } }")
    assert "ret i32 42" in run("mlir-translate", "--mlir-to-llvmir", source=optimized)
    for tool in ("mlir-opt", "mlir-translate", "mlir-runner", "mlir-reduce",
                 "mlir-query", "mlir-rewrite"):
        assert run(tool, "--help")


def check_targets(installed):
    library = ctypes.CDLL(str(next((installed / "_mlir_libs").glob("libLLVM.so*"))))
    library.LLVMGetTargetFromTriple.argtypes = [ctypes.c_char_p,
                                               ctypes.POINTER(ctypes.c_void_p),
                                               ctypes.POINTER(ctypes.c_char_p)]
    library.LLVMGetTargetFromTriple.restype = ctypes.c_int
    for backend, triple in (("X86", b"x86_64-unknown-linux-gnu"),
                           ("NVPTX", b"nvptx64-nvidia-cuda"),
                           ("AMDGPU", b"amdgcn-amd-amdhsa"),
                           ("RISCV", b"riscv64-unknown-linux-gnu")):
        getattr(library, f"LLVMInitialize{backend}TargetInfo")()
        getattr(library, f"LLVMInitialize{backend}Target")()
        target, error = ctypes.c_void_p(), ctypes.c_char_p()
        assert library.LLVMGetTargetFromTriple(triple, ctypes.byref(target),
                                              ctypes.byref(error)) == 0, error.value
        assert target.value


def check_runtime(installed):
    libraries = installed / "_mlir_libs"
    for name in ("mlir_async_runtime", "mlir_c_runner_utils", "mlir_runner_utils",
                 "mlir_float16_utils", "mlir_apfloat_wrappers", "mlir_arm_sme_abi_stubs",
                 "mlir_arm_runner_utils"):
        ctypes.CDLL(str(libraries / f"lib{name}.so"))
    for header in ("mlir-c/IR.h", "mlir/IR/OpBase.td"):
        assert (libraries / "include" / header).is_file(), header
    with ir.Context():
        module = ir.Module.parse("""
            module {
              func.func private @_mlir_ciface_nanoTime() -> i64
              func.func @read_clock() -> i64 attributes {llvm.emit_c_interface} {
                %time = func.call @_mlir_ciface_nanoTime() : () -> i64
                return %time : i64
              }
            }
        """)
        PassManager.parse("builtin.module(convert-func-to-llvm)").run(module.operation)
        engine = ExecutionEngine(module, shared_libs=[str(libraries / "libmlir_runner_utils.so")])
        time = ctypes.c_int64()
        engine.invoke("read_clock", ctypes.byref(time))
        assert time.value > 0, time.value


def main():
    installed = distribution("mlir-python-bindings").locate_file("mlir").resolve()
    assert Path(ir.__file__).resolve().is_relative_to(installed), ir.__file__
    check_core()
    check_linalg()
    check_gpu_codegen()
    check_tools(installed)
    check_targets(installed)
    check_runtime(installed)
    print(f"Python {sys.version.split()[0]}: {ir.__file__}")
    print("PASS: IR/NumPy, tensor linalg lowering, LLVM IR, CPU JIT, GPU ISA, "
          "four LLVM targets, native tools, runtimes, and headers")


if __name__ == "__main__":
    main()
