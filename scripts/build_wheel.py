# /// script
# requires-python = ">=3.12"
# dependencies = ["wheel==0.48.0", "auditwheel==6.8.2", "patchelf==0.19.3.0", "abi3audit==0.0.26"]
# ///
"""Package the existing Linux MLIR build as an audited abi3 wheel."""

import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory

from wheel.wheelfile import WheelFile


def run(*args):
    subprocess.run(args, check=True)


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "llvm-project/build"
    package = build / "tools/mlir/python_packages/mlir_core/mlir"
    if sys.platform != "linux":
        raise SystemExit("Wheel packaging currently supports Linux only.")
    if not (package / "_mlir_libs/_mlir.abi3.so").is_file():
        raise SystemExit("Build the abi3 bindings first: bash scripts/llvm_build.sh")
    config = (build / "include/llvm/Config/llvm-config.h").read_text()
    version = ".".join(
        re.search(rf"#define LLVM_VERSION_{part} (\d+)", config)[1]
        for part in ("MAJOR", "MINOR", "PATCH")
    )
    name = f"mlir_python_bindings-{version}"
    tag = f"cp312-abi3-{sysconfig.get_platform().replace('-', '_').replace('.', '_')}"
    output = root / "dist"
    output.mkdir(exist_ok=True)
    scratch = root / "debug_agent"
    if not scratch.exists():
        scratch.mkdir()
        (scratch / ".gitignore").write_text("*\n!AGENTS.md\n")

    with TemporaryDirectory(prefix="wheel-", dir=scratch) as temporary:
        staging = Path(temporary) / "package"
        shutil.copytree(package, staging / "mlir", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        libraries = staging / "mlir/_mlir_libs"
        binaries = sorted(path for path in libraries.iterdir() if ".so" in path.name)
        if any(".cpython-" in path.name for path in binaries):
            raise SystemExit("Found non-abi3 extensions; rebuild with stable ABI enabled.")
        for library in binaries:
            run("patchelf", "--set-rpath", "$ORIGIN", str(library))
        run("abi3audit", "--strict", "--assume-minimum-abi3", "3.12",
            *map(str, libraries.glob("*.so")))

        metadata = staging / f"{name}.dist-info"
        metadata.mkdir()
        (metadata / "WHEEL").write_text(
            f"Wheel-Version: 1.0\nGenerator: mlir-python-bindings\nRoot-Is-Purelib: false\nTag: {tag}\n"
        )
        requirements = (root / "llvm-project/mlir/python/requirements.txt").read_text()
        dependencies = [
            line.strip() for line in requirements.splitlines()
            if line.strip() and not line.startswith(("#", "nanobind"))
        ]
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.4\nName: mlir-python-bindings\nVersion: {version}\n"
            "Summary: MLIR Python bindings with the CPython stable ABI\n"
            "Requires-Python: >=3.12\n"
            "License-Expression: Apache-2.0 WITH LLVM-exception AND BSD-3-Clause AND MIT\n"
            "License-File: licenses/LLVM.txt\nLicense-File: licenses/nanobind.txt\n"
            "License-File: licenses/robin_map.txt\n"
            + "".join(f"Requires-Dist: {dependency}\n" for dependency in dependencies)
        )
        licenses = metadata / "licenses"
        licenses.mkdir()
        shutil.copyfile(root / "llvm-project/llvm/LICENSE.TXT", licenses / "LLVM.txt")
        nanobind_license = subprocess.check_output(
            [str(root / ".venv/bin/python"), "-c",
             "from importlib.metadata import distribution; "
             "d = distribution('nanobind'); "
             "print(next(d.locate_file(f) for f in d.files if str(f).endswith('licenses/LICENSE')))"],
            text=True,
        ).strip()
        shutil.copyfile(nanobind_license, licenses / "nanobind.txt")
        robin_map = Path(nanobind_license).parents[2] / "nanobind/ext/robin_map/include/tsl/robin_map.h"
        (licenses / "robin_map.txt").write_text(robin_map.read_text().split("*/", 1)[0] + "*/\n")
        wheel = Path(temporary) / f"{name}-{tag}.whl"
        with WheelFile(wheel, "w") as archive:
            archive.write_files(staging)
        repaired_directory = Path(temporary) / "repaired"
        run("auditwheel", "repair", "--wheel-dir", str(repaired_directory), str(wheel))
        for repaired in repaired_directory.glob("*.whl"):
            run("abi3audit", "--strict", "--summary", str(repaired))
            destination = output / repaired.name
            shutil.copyfile(repaired, destination)
            print(destination.relative_to(root))


if __name__ == "__main__":
    main()
