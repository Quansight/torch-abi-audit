"""Shared pytest fixtures.

The fixture-builder logic compiles tiny C/C++ extensions on demand against the
running interpreter (and against ``torch`` when available). If no compiler is
found, the fixtures skip cleanly so the rest of the suite still runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

_SRC = Path(__file__).parent / "fixtures" / "src"


def _have_compiler(name: str) -> str | None:
    return shutil.which(name)


def _compile(
    *,
    src: Path,
    out: Path,
    is_cpp: bool,
    extra_cflags: list[str],
    extra_ldflags: list[str],
    include_dirs: list[str],
) -> None:
    compiler = _have_compiler("c++" if is_cpp else "cc") or _have_compiler(
        "g++" if is_cpp else "gcc"
    )
    if compiler is None:
        pytest.skip(f"no C{'++' if is_cpp else ''} compiler found")
    cmd = [
        compiler,
        "-shared",
        "-fPIC",
        "-O0",
        "-o",
        str(out),
        str(src),
    ]
    for d in include_dirs:
        cmd += ["-I", d]
    cmd += extra_cflags
    cmd += extra_ldflags
    if sys.platform == "darwin":
        # Mach-O's linker rejects undefined Python C API symbols at link time;
        # defer resolution to load time, which is how setuptools builds
        # Python extensions on macOS.
        cmd += ["-undefined", "dynamic_lookup"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # Don't skip on compile failure — a present compiler that fails to
        # produce a fixture is a real bug, not an environment issue. Skipping
        # silently masks linker regressions in CI.
        raise RuntimeError(
            f"compile failed (exit {proc.returncode}):\n"
            f"$ {' '.join(cmd)}\n"
            f"{proc.stderr.strip()}"
        )


@pytest.fixture(scope="session")
def cpython_stable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("ext-stable") / "fixture_stable.abi3.so"
    inc = sysconfig.get_paths()["include"]
    _compile(
        src=_SRC / "cpython_stable.c",
        out=out,
        is_cpp=False,
        extra_cflags=["-DPy_LIMITED_API=0x030B0000"],
        extra_ldflags=[],
        include_dirs=[inc],
    )
    return out


@pytest.fixture(scope="session")
def cpython_unstable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("ext-unstable") / "fixture_unstable.so"
    inc = sysconfig.get_paths()["include"]
    _compile(
        src=_SRC / "cpython_unstable.c",
        out=out,
        is_cpp=False,
        extra_cflags=[],
        extra_ldflags=[],
        include_dirs=[inc],
    )
    return out


def _torch_paths() -> tuple[list[str], list[str]] | None:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return None
    base = Path(torch.__file__).parent
    includes = [
        str(base / "include"),
        str(base / "include" / "torch" / "csrc" / "api" / "include"),
    ]
    libs = [f"-L{base / 'lib'}", "-ltorch", "-ltorch_cpu", "-lc10"]
    return includes, libs


@pytest.fixture(scope="session")
def torch_stable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    paths = _torch_paths()
    if paths is None:
        pytest.skip("torch is not importable")
    includes, libs = paths
    out = tmp_path_factory.mktemp("ext-torch-stable") / "fixture_torch_stable.so"
    _compile(
        src=_SRC / "torch_stable.cpp",
        out=out,
        is_cpp=True,
        extra_cflags=["-std=c++17", "-DTORCH_TARGET_VERSION=0x020a000000000000"],
        extra_ldflags=libs,
        include_dirs=includes,
    )
    return out


@pytest.fixture(scope="session")
def torch_unstable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    paths = _torch_paths()
    if paths is None:
        pytest.skip("torch is not importable")
    includes, libs = paths
    out = tmp_path_factory.mktemp("ext-torch-unstable") / "fixture_torch_unstable.so"
    env = os.environ.get("CXXFLAGS", "")
    _compile(
        src=_SRC / "torch_unstable.cpp",
        out=out,
        is_cpp=True,
        extra_cflags=["-std=c++17"] + env.split(),
        extra_ldflags=libs,
        include_dirs=includes,
    )
    return out
