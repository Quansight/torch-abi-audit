"""Shared pytest fixtures.

The fixture-builder logic compiles tiny C/C++ extensions on demand against the
running interpreter (and against ``torch`` when available). If no compiler is
found, the fixtures skip cleanly so the rest of the suite still runs.

Windows is the exception: the fixtures are built with MSVC, and a configured
toolchain is required. Run the suite from a Visual Studio developer prompt (or
from any shell with the MSVC environment initialised), otherwise a missing
``cl`` is a test failure rather than a skip — a silently skipped Windows run
would hide every compiled-fixture test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

_SRC = Path(__file__).parent / "fixtures" / "src"

#: Filename suffix for a compiled extension module on this host.
EXTENSION_SUFFIX = ".pyd" if sys.platform == "win32" else ".so"

#: Filename suffix for a bundled (non-extension) shared library on this host.
LIBRARY_SUFFIX = (
    ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
)


def _have_compiler(name: str) -> str | None:
    return shutil.which(name)


def _compile(
    *,
    src: Path,
    out: Path,
    is_cpp: bool = False,
    include_dirs: Sequence[str] = (),
    defines: Sequence[str] = (),
    stdlib: str | None = None,
    libraries: Sequence[str] = (),
    library_dirs: Sequence[str] = (),
    link_python: bool = False,
    extra_cflags: Sequence[str] = (),
) -> None:
    """Compile ``src`` into the shared library ``out``.

    ``extra_cflags`` carries raw ``$CXXFLAGS`` entries and is Unix-only; the
    variable is a POSIX convention and its values are not valid MSVC flags.
    """
    # The compiler runs from the output directory so MSVC's .obj/.exp/.lib
    # intermediates stay out of the repository, which needs absolute paths.
    src = src.resolve()
    out = out.resolve()
    include_dirs = [str(Path(d).resolve()) for d in include_dirs]
    library_dirs = [str(Path(d).resolve()) for d in library_dirs]

    if sys.platform == "win32":
        cmd = _msvc_command(
            src=src,
            out=out,
            is_cpp=is_cpp,
            include_dirs=include_dirs,
            defines=defines,
            stdlib=stdlib,
            libraries=libraries,
            library_dirs=library_dirs,
            link_python=link_python,
        )
    else:
        cmd = _unix_command(
            src=src,
            out=out,
            is_cpp=is_cpp,
            include_dirs=include_dirs,
            defines=defines,
            stdlib=stdlib,
            libraries=libraries,
            library_dirs=library_dirs,
            extra_cflags=extra_cflags,
        )

    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False, cwd=out.parent
    )
    if proc.returncode != 0:
        # Don't skip on compile failure — a present compiler that fails to
        # produce a fixture is a real bug, not an environment issue. Skipping
        # silently masks linker regressions in CI.
        raise RuntimeError(
            f"compile failed (exit {proc.returncode}):\n"
            f"$ {' '.join(cmd)}\n"
            f"{(proc.stderr or proc.stdout).strip()}"
        )


def _unix_command(
    *,
    src: Path,
    out: Path,
    is_cpp: bool,
    include_dirs: Sequence[str],
    defines: Sequence[str],
    stdlib: str | None,
    libraries: Sequence[str],
    library_dirs: Sequence[str],
    extra_cflags: Sequence[str],
) -> list[str]:
    compiler = _have_compiler("c++" if is_cpp else "cc") or _have_compiler(
        "g++" if is_cpp else "gcc"
    )
    if compiler is None:
        pytest.skip(f"no C{'++' if is_cpp else ''} compiler found")
    cmd = [compiler, "-shared", "-fPIC", "-O0", "-o", str(out), str(src)]
    for d in include_dirs:
        cmd += ["-I", d]
    cmd += [f"-D{define}" for define in defines]
    if stdlib is not None:
        cmd.append(f"-std={stdlib}")
    cmd += list(extra_cflags)
    cmd.extend(f"-L{directory}" for directory in library_dirs)
    cmd.extend(f"-l{library}" for library in libraries)
    if sys.platform == "darwin":
        # Mach-O's linker rejects undefined Python C API symbols at link time;
        # defer resolution to load time, which is how setuptools builds
        # Python extensions on macOS.
        cmd += ["-undefined", "dynamic_lookup"]
    return cmd


def _msvc_command(
    *,
    src: Path,
    out: Path,
    is_cpp: bool,
    include_dirs: Sequence[str],
    defines: Sequence[str],
    stdlib: str | None,
    libraries: Sequence[str],
    library_dirs: Sequence[str],
    link_python: bool,
) -> list[str]:
    cl = _have_compiler("cl")
    if cl is None:
        pytest.fail(
            "cl.exe not found: run pytest from a Visual Studio developer prompt, "
            "or from a shell with the MSVC environment initialised "
            "(see 'Development' in the README)"
        )
    # /MD matches CPython's own CRT; /LD produces the DLL that a .pyd really is.
    cmd = [cl, "/nologo", "/LD", "/MD", "/Od"]
    if is_cpp:
        cmd.append("/EHsc")
        if stdlib is not None:
            # Ask for C++20 rather than transliterating -std=c++17: torch 2.13
            # and later headers require it, and this branch only ever sees the
            # torch fixtures.
            cmd.append("/std:c++20")
    cmd.extend(f"/D{define}" for define in defines)
    cmd.extend(f"/I{include}" for include in include_dirs)
    cmd.append(str(src))
    cmd.extend(["/link", f"/OUT:{out}"])
    cmd.extend(f"/LIBPATH:{directory}" for directory in library_dirs)
    cmd.extend(f"{library}.lib" for library in libraries)
    if link_python:
        # PE has no unresolved symbols, unlike ELF, so the import library is
        # required. Its directory also satisfies the python3.lib reference that
        # a limited-API build emits.
        import_lib = _python_import_library(
            limited_api=any(d.startswith("Py_LIMITED_API") for d in defines)
        )
        cmd.extend([f"/LIBPATH:{import_lib.parent}", str(import_lib)])
    return cmd


def _python_import_library(*, limited_api: bool) -> Path:
    """The interpreter's import library, for linking fixtures against CPython.

    CPython installs two: ``python3XX.lib`` with every symbol and ``python3.lib``
    restricted to the stable ABI. Limited-API builds must use the latter.
    """
    base = Path(sysconfig.get_config_var("installed_base") or sys.base_prefix)
    name = (
        "python3.lib"
        if limited_api
        else f"python{sys.version_info.major}{sys.version_info.minor}.lib"
    )
    path = base / "libs" / name
    if not path.is_file():
        pytest.fail(
            f"missing Python import library {path}; a Windows CPython install "
            "normally ships one, so check that the interpreter is intact"
        )
    return path


@pytest.fixture(scope="session")
def compile_library() -> Callable[[Path, Path], Path]:
    """Build an arbitrary library that does not import Python.

    Used to produce a stand-in for a bundled (non-extension) shared library.
    """

    def build(src: Path, out: Path) -> Path:
        _compile(src=src, out=out)
        return out

    return build


@pytest.fixture(scope="session")
def cpython_stable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("ext-stable") / (
        f"fixture_stable.abi3{EXTENSION_SUFFIX}"
    )
    inc = sysconfig.get_paths()["include"]
    _compile(
        src=_SRC / "cpython_stable.c",
        out=out,
        include_dirs=[inc],
        defines=["Py_LIMITED_API=0x030B0000"],
        link_python=True,
    )
    return out


@pytest.fixture(scope="session")
def cpython_unstable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("ext-unstable") / (
        f"fixture_unstable{EXTENSION_SUFFIX}"
    )
    inc = sysconfig.get_paths()["include"]
    _compile(
        src=_SRC / "cpython_unstable.c",
        out=out,
        include_dirs=[inc],
        link_python=True,
    )
    return out


@pytest.fixture(scope="session")
def cpython_pymodexport_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if sys.version_info < (3, 15):
        pytest.skip("PyModExport requires Python 3.15+")
    out = tmp_path_factory.mktemp("ext-pymodexport") / (
        f"fixture_pymodexport{EXTENSION_SUFFIX}"
    )
    _compile(
        src=_SRC / "cpython_pymodexport.c",
        out=out,
        include_dirs=[sysconfig.get_paths()["include"]],
        link_python=True,
    )
    return out


def _torch_paths() -> tuple[list[str], list[str], list[str]] | None:
    """``(includes, library_dirs, libraries)`` for linking against torch."""
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return None
    base = Path(torch.__file__).parent
    includes = [
        str(base / "include"),
        str(base / "include" / "torch" / "csrc" / "api" / "include"),
    ]
    return includes, [str(base / "lib")], ["torch", "torch_cpu", "c10"]


@pytest.fixture(scope="session")
def torch_stable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    paths = _torch_paths()
    if paths is None:
        pytest.skip("torch is not importable")
    includes, library_dirs, libraries = paths
    out = tmp_path_factory.mktemp("ext-torch-stable") / (
        f"fixture_torch_stable{EXTENSION_SUFFIX}"
    )
    _compile(
        src=_SRC / "torch_stable.cpp",
        out=out,
        is_cpp=True,
        include_dirs=includes,
        defines=["TORCH_TARGET_VERSION=0x020a000000000000"],
        stdlib="c++17",
        libraries=libraries,
        library_dirs=library_dirs,
    )
    return out


@pytest.fixture(scope="session")
def torch_unstable_so(tmp_path_factory: pytest.TempPathFactory) -> Path:
    paths = _torch_paths()
    if paths is None:
        pytest.skip("torch is not importable")
    includes, library_dirs, libraries = paths
    out = tmp_path_factory.mktemp("ext-torch-unstable") / (
        f"fixture_torch_unstable{EXTENSION_SUFFIX}"
    )
    env = os.environ.get("CXXFLAGS", "")
    _compile(
        src=_SRC / "torch_unstable.cpp",
        out=out,
        is_cpp=True,
        include_dirs=includes,
        stdlib="c++17",
        libraries=libraries,
        library_dirs=library_dirs,
        extra_cflags=env.split(),
    )
    return out
