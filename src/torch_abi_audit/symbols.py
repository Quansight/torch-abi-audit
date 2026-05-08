"""Extract undefined dynamic symbols from compiled extension modules."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .demangle import demangle_symbol


def _nm_command(path: Path) -> list[str]:
    """Build the nm invocation.

    ``-j`` prints just the symbol names (no type column or address); ``-u``
    filters to undefined-only. On Linux we also pass ``-D`` to read the
    dynamic symbol table (Mach-O has a unified table on macOS).

    The ``-j`` form is used on both platforms because BSD / macOS nm with
    ``-u`` alone elides the type column, so a parser that expected the GNU
    ``U <name>`` shape silently dropped every line.

    We deliberately don't pass ``-C`` — pycxxfilt handles C++ demangling
    in :mod:`.demangle`.
    """
    flags = "uj"
    if sys.platform != "darwin":
        flags += "D"
    return ["nm", f"-{flags}", str(path)]


def extract_undefined_symbols(path: Path) -> list[str]:
    """Return demangled undefined symbols from ``path``.

    Empty list if nm errors out (e.g. the file isn't a recognised object file).
    """
    if sys.platform == "win32":
        raise RuntimeError(
            "Windows is not yet supported (PE/COFF parsing via dumpbin is not implemented)"
        )
    if not shutil.which("nm"):
        hint = "Xcode Command Line Tools" if sys.platform == "darwin" else "binutils"
        raise RuntimeError(f"'nm' not found in PATH (install {hint})")

    proc = subprocess.run(
        _nm_command(path), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 and not proc.stdout:
        return []

    symbols: list[str] = []
    on_darwin = sys.platform == "darwin"
    for line in proc.stdout.splitlines():
        sym = line.strip()
        if not sym:
            continue
        # Mach-O linkers prepend `_` to every external symbol. Strip exactly
        # one leading underscore so downstream classifiers see the same names
        # as on Linux.
        if on_darwin and sym.startswith("_"):
            sym = sym[1:]
        symbols.append(demangle_symbol(sym))
    return symbols


def has_pyinit_symbol(path: Path) -> bool:
    """Return True if ``path`` defines a ``PyInit_*`` symbol (Python extension marker).

    On macOS Mach-O there is one symbol table; ``-g`` shows external symbols.
    On Linux we want exported dynamic symbols, so ``-D``.
    """
    if not shutil.which("nm"):
        return False
    args = ["nm", "-g", str(path)] if sys.platform == "darwin" else ["nm", "-D", str(path)]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0 and not proc.stdout:
        return False
    for line in proc.stdout.splitlines():
        parts = line.split()
        # Defined symbols have 3 tokens: "<addr> <type> <name>".
        # Undefined have 2: "U <name>" — those won't satisfy len >= 3.
        if len(parts) >= 3 and parts[-1].lstrip("_").startswith("PyInit_"):
            return True
    return False


def is_extension_module(path: Path) -> bool:
    """True iff ``path`` is a CPython extension module (vs. a bundled shared library).

    The only reliable signal is a defined ``PyInit_*`` symbol — the entry point
    Python's import machinery looks up. Filename tags like ``abi3`` or
    ``cpython`` are routinely used by torch ecosystem packages for libraries
    loaded via ``STABLE_TORCH_LIBRARY`` rather than Python's importer, so they
    aren't a reliable signal on their own.
    """
    if not path.is_file():
        return False
    if not path.name.endswith((".so", ".pyd", ".dylib")):
        return False
    return has_pyinit_symbol(path)


def find_compiled_libraries(directory: Path) -> list[Path]:
    """Recursively find every ``.so`` / ``.pyd`` / ``.dylib`` under ``directory``.

    Includes both Python extension modules and bundled internal shared
    libraries (e.g. ``torch/lib/libtorch_cpu.so``,
    ``torchcodec/libtorchcodec_core8.so``) — callers split the two via
    :func:`is_extension_module`.
    """
    out: set[Path] = set()
    for ext in ("*.so", "*.pyd", "*.dylib"):
        for p in directory.rglob(ext):
            if p.is_file():
                out.add(p)
    return sorted(out)


def find_extension_modules(directory: Path) -> list[Path]:
    """Recursively find CPython extension modules under ``directory``."""
    return [p for p in find_compiled_libraries(directory) if is_extension_module(p)]
