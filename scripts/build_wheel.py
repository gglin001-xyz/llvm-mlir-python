# /// script
# requires-python = ">=3.12"
# dependencies = ["wheel==0.48.0", "auditwheel==6.8.2", "patchelf==0.19.3.0", "abi3audit==0.0.26"]
# ///
"""Package the existing Linux MLIR build as an audited abi3 wheel."""

import json
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


def bundle_libraries(build, libraries, binaries):
    """Include build-tree dependencies, leaving system libraries to auditwheel."""
    pending = list(binaries)
    while pending:
        binary = pending.pop()
        needed = subprocess.check_output(["patchelf", "--print-needed", str(binary)], text=True)
        for name in needed.splitlines():
            source = build / "lib" / name
            destination = libraries / name
            if source.is_file() and not destination.exists():
                shutil.copyfile(source, destination)
                pending.append(destination)
        rpath = "$ORIGIN" if binary.parent == libraries else "$ORIGIN/../_mlir_libs"
        run("patchelf", "--set-rpath", rpath, str(binary))


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
    contents = json.loads((root / "scripts/wheel_contents.json").read_text())
    scratch = root / "debug_agent"
    if not scratch.exists():
        scratch.mkdir()
        (scratch / ".gitignore").write_text("*\n!AGENTS.md\n")

    with TemporaryDirectory(prefix="wheel-", dir=scratch) as temporary:
        staging = Path(temporary) / "package"
        shutil.copytree(package, staging / "mlir", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        libraries = staging / "mlir/_mlir_libs"
        # Wheels cannot preserve symlinks. Keep the SONAME file without a second copy.
        for source in (package / "_mlir_libs").glob("*.so"):
            if source.is_symlink() and source.resolve().parent == source.parent.resolve():
                (libraries / source.name).unlink()
        for runtime in contents["runtimes"]:
            shutil.copyfile(build / "lib" / f"lib{runtime}.so", libraries / f"lib{runtime}.so")
        tools = staging / "mlir/bin"
        tools.mkdir()
        for tool in contents["tools"]:
            shutil.copy2(build / "bin" / tool, tools / tool)
        (staging / "mlir/_tools.py").write_text(
            "import os\nimport sys\nfrom pathlib import Path\n\n"
            "def main():\n"
            "    tool = Path(__file__).with_name('bin') / Path(sys.argv[0]).name\n"
            "    os.execv(tool, [str(tool), *sys.argv[1:]])\n"
        )
        for includes in (root / "llvm-project/llvm/include", build / "include",
                         root / "llvm-project/mlir/include", build / "tools/mlir/include"):
            for header in includes.rglob("*"):
                if header.is_file() and header.suffix in {".h", ".inc", ".td", ".def"}:
                    destination = libraries / "include" / header.relative_to(includes)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(header, destination)
        binaries = sorted(path for path in libraries.iterdir() if ".so" in path.name)
        if any(".cpython-" in path.name for path in binaries):
            raise SystemExit("Found non-abi3 extensions; rebuild with stable ABI enabled.")
        bundle_libraries(build, libraries, [*binaries, *tools.iterdir()])
        run("abi3audit", "--strict", "--assume-minimum-abi3", "3.12",
            *map(str, libraries.glob("*.so")))

        metadata = staging / f"{name}.dist-info"
        metadata.mkdir()
        (metadata / "entry_points.txt").write_text(
            "[console_scripts]\n" + "".join(f"{tool} = mlir._tools:main\n" for tool in contents["tools"])
        )
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
            "License-File: LLVM.txt\nLicense-File: nanobind.txt\n"
            "License-File: robin_map.txt\n"
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
