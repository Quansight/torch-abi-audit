"""Read the imported and exported symbol names from compiled libraries.

Two backends, picked by the file's own magic bytes rather than the host OS:

* **PE/COFF** (Windows ``.pyd`` / ``.dll``) — ``dumpbin`` when it is on PATH
  (only inside a Visual Studio developer prompt), otherwise the built-in
  parser in :mod:`.pe`. Neither route needs Windows, so Windows wheels can be
  audited from macOS or Linux too.
* **ELF / Mach-O** — ``nm`` from binutils / Xcode Command Line Tools.

Sniffing the file means a given library is reported the same way regardless of
where the tool runs; an unrecognised format falls back to ``nm``, which is the
historical behaviour.

Callers ask for the same library twice (once to classify it as an extension
module, once to inspect it), so results are memoised on the stat signature —
PE images shipped by torch reach hundreds of megabytes. The cache key is the
resolved path, because a relative path plus size and mtime does not identify a
file: two directories can each hold a different, equally sized file that was
written in the same timestamp tick.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import dumpbin, pe
from .demangle import demangle_symbol

#: Every format the reader understands. Only used for a file the user names
#: explicitly: the built-in PE parser is portable, so a Windows ``.pyd``/``.dll``
#: can be inspected by path on any host. ELF and Mach-O still depend on the
#: host's ``nm``, so this is not a cross-platform scan capability.
ALL_LIBRARY_SUFFIXES = (".so", ".pyd", ".dylib", ".dll")

#: Formats a directory scan collects on this host. POSIX keeps the set it has
#: always used; Windows adds ``.dll`` because that is where its bundled libraries
#: live (``torch/lib/torch_cpu.dll``) alongside ``.pyd`` extension modules.
LIBRARY_SUFFIXES = (
    (".pyd", ".dll")
    if sys.platform == "win32"
    else (".so", ".pyd", ".dylib")
)

_ELF_MAGIC = b"\x7fELF"
_MACHO_MAGICS = frozenset(
    {
        b"\xfe\xed\xfa\xce",  # 32-bit big-endian
        b"\xce\xfa\xed\xfe",  # 32-bit little-endian
        b"\xfe\xed\xfa\xcf",  # 64-bit big-endian
        b"\xcf\xfa\xed\xfe",  # 64-bit little-endian
        b"\xca\xfe\xba\xbe",  # universal (fat) binary
        b"\xbe\xba\xfe\xca",
    }
)


@dataclass(frozen=True, slots=True)
class BinarySymbols:
    """Symbol names read from one compiled library.

    ``imports`` are references to symbols defined outside the library — the
    ELF dynamic symbol table's undefined entries, or the PE import directory —
    already demangled. ``exports`` are the names the library defines, left
    undemangled: they are only used to spot Python module entry points, which
    are plain C names. ``libraries`` names the dependencies imports come from,
    which is how a Windows Stable ABI extension is distinguished from one
    pinned to a versioned ``python3XX.dll``. ``error`` means nothing could be
    read; ``incomplete`` means some symbols were recovered but the table could
    not be followed to its end.
    """

    imports: tuple[str, ...] = ()
    exports: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    #: Set when nothing could be read at all; verdicts are then placeholders.
    error: str | None = None
    #: Set when part of the table was unreadable but names were recovered.
    incomplete: str | None = None


def read_symbols(path: Path) -> BinarySymbols:
    """Read the symbol tables of ``path``.

    Empty when the file cannot be read, mirroring ``nm``'s leniency for files
    that aren't recognised object files.
    """
    try:
        resolved = Path(path).resolve()
        stat = resolved.stat()
    except OSError:
        return BinarySymbols()
    return _read_symbols_cached(str(resolved), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=64)
def _read_symbols_cached(path: str, _size: int, _mtime_ns: int) -> BinarySymbols:
    p = Path(path)
    try:
        file_format = _file_format(p)
    except OSError:
        return BinarySymbols()
    if file_format == "pe":
        return _read_pe(p)
    return _read_nm(p)


def _file_format(path: Path) -> str | None:
    """Sniff the container format from the leading magic bytes."""
    with path.open("rb") as f:
        head = f.read(4)
    if head.startswith(b"MZ"):
        return "pe"
    if head == _ELF_MAGIC:
        return "elf"
    if head in _MACHO_MAGICS:
        return "macho"
    return None


def _read_pe(path: Path) -> BinarySymbols:
    tables = _pe_tables(path)
    return BinarySymbols(
        imports=tuple(demangle_symbol(name) for name in tables.imports),
        exports=tables.exports,
        libraries=tables.libraries,
        error=tables.error,
        incomplete=tables.incomplete,
    )


@dataclass(frozen=True, slots=True)
class _PETables:
    imports: tuple[str, ...] = ()
    exports: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    error: str | None = None
    incomplete: str | None = None


def _pe_tables(path: Path) -> _PETables:
    """Import and export data for one PE image.

    ``dumpbin`` wins when it is on PATH, mirroring the ``nm``-first behaviour on
    ELF/Mach-O; the built-in parser covers ordinary installs, where no Visual
    Studio prompt is active, and every non-Windows host.

    A failed, partial or empty ``dumpbin`` run falls through to the parser
    rather than reporting an empty table: a silently clean verdict is worse than
    paying a few milliseconds, and it keeps the audit stable if a dumpbin
    release rewords its output. (dumpbin is also 10-230x slower, so the fallback
    is the path most users take.)
    """
    if dumpbin.find_dumpbin():
        try:
            tables = dumpbin.read_dumpbin(path)
        except (dumpbin.DumpbinError, OSError):
            pass
        else:
            # All three tables must have parsed. A reworded dumpbin release (or a
            # partially readable directory) can yield names for one table and
            # nothing for the rest; trusting that would silently demote an
            # extension module to a bundled library, because entry-point
            # detection reads only ``exports`` — and an empty ``libraries``
            # would skip the ``python3XX.dll`` pinning check, making an
            # abi3-tagged module look compliant. An image with imports always
            # names at least one DLL, and the parser can recover names that
            # dumpbin's heuristic misses, so re-parsing is cheap insurance.
            if tables.imports and tables.exports and tables.libraries:
                return _PETables(
                    imports=tables.imports,
                    exports=tables.exports,
                    libraries=tables.libraries,
                )
    try:
        data = pe.read_pe(path)
    except (pe.PEFormatError, OSError) as exc:
        return _PETables(error=f"PE parse failed: {exc}")
    message = "; ".join(data.errors) or None
    # Nothing recovered means the file is unusable; anything recovered means the
    # verdict stands but the read was incomplete and must not look clean.
    recovered = bool(data.imports or data.exports or data.libraries)
    return _PETables(
        imports=data.imports,
        exports=data.exports,
        libraries=data.libraries,
        error=None if recovered else message,
        incomplete=message if recovered else None,
    )


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


def _read_nm(path: Path) -> BinarySymbols:
    if not shutil.which("nm"):
        hint = "Xcode Command Line Tools" if sys.platform == "darwin" else "binutils"
        raise RuntimeError(f"'nm' not found in PATH (install {hint})")
    # ELF/Mach-O dependency names are not read: the version-pinned-versus-stable
    # DLL question is Windows-specific, and no other platform needs the answer.
    return BinarySymbols(imports=_nm_imports(path), exports=_nm_exports(path))


def _nm_imports(path: Path) -> tuple[str, ...]:
    proc = subprocess.run(
        _nm_command(path), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 and not proc.stdout:
        return ()

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
    return tuple(symbols)


def _nm_exports(path: Path) -> tuple[str, ...]:
    """Defined external symbols, via the same nm binary.

    On macOS Mach-O there is one symbol table, so ``-g`` shows external
    symbols; on Linux we want exported dynamic symbols, so ``-D``.
    """
    args = (
        ["nm", "-g", str(path)]
        if sys.platform == "darwin"
        else ["nm", "-D", str(path)]
    )
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0 and not proc.stdout:
        return ()
    names: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        # Defined symbols have 3 tokens: "<addr> <type> <name>".
        # Undefined have 2: "U <name>" — those won't satisfy len >= 3.
        if len(parts) >= 3:
            names.append(parts[-1])
    return tuple(names)


def extract_undefined_symbols(path: Path) -> list[str]:
    """Return demangled undefined symbols from ``path``.

    Empty list if the file isn't a recognised object file (or can't be read).
    """
    return list(read_symbols(path).imports)


_MODULE_ENTRYPOINT_PREFIXES = (
    "PyInit_",
    "PyInitU_",
    "PyModExport_",
    "PyModExportU_",
)


def is_module_entrypoint(name: str) -> bool:
    """True if ``name`` is a Python extension entry-point symbol (any leading
    underscores from Mach-O already tolerated)."""
    return name.lstrip("_").startswith(_MODULE_ENTRYPOINT_PREFIXES)


def has_module_entrypoint(path: Path) -> bool:
    """Return True if ``path`` defines a Python module entry point.

    Recognises the classic ``PyInit_*`` hook and the PEP 793 ``PyModExport_*``
    hook (plus their ``*U_`` non-ASCII variants), looking at the library's
    exported names.
    """
    try:
        symbols = read_symbols(path)
    except RuntimeError:
        return False
    return any(is_module_entrypoint(name) for name in symbols.exports)


def is_extension_module(path: Path) -> bool:
    """True iff ``path`` is a CPython extension module (vs. a bundled shared library).

    The only reliable signal is a defined module entry point (``PyInit_*`` or the
    PEP 793 ``PyModExport_*``) — the symbol Python's import machinery looks up.
    Filename tags like ``abi3`` or ``cpython`` are routinely used by torch
    ecosystem packages for libraries loaded via ``STABLE_TORCH_LIBRARY`` rather
    than Python's importer, so they aren't a reliable signal on their own.
    """
    if not path.is_file():
        return False
    if not path.name.endswith(ALL_LIBRARY_SUFFIXES):
        return False
    return has_module_entrypoint(path)


def is_scannable_library(path: Path) -> bool:
    """True if a directory scan on this host would collect ``path``.

    Reads :data:`LIBRARY_SUFFIXES` at call time, so the rule a package scan and
    the site-packages top-level check apply cannot drift apart.
    """
    return path.name.endswith(LIBRARY_SUFFIXES)


def find_compiled_libraries(directory: Path) -> list[Path]:
    """Recursively find every compiled library under ``directory``.

    Collects :data:`LIBRARY_SUFFIXES`, so a scan returns the formats this host
    actually uses — ``.so``/``.pyd``/``.dylib`` on POSIX, ``.pyd``/``.dll`` on
    Windows. Includes both Python extension modules and bundled internal shared
    libraries (e.g. ``torch/lib/libtorch_cpu.so``,
    ``torchcodec/lib/torchcodec_core8.so``, ``torch/lib/torch_cpu.dll``) —
    callers split the two via :func:`is_extension_module`.
    """
    out: set[Path] = set()
    for ext in ("*" + suffix for suffix in LIBRARY_SUFFIXES):
        for p in directory.rglob(ext):
            if p.is_file():
                out.add(p)
    return sorted(out)


def find_extension_modules(directory: Path) -> list[Path]:
    """Recursively find CPython extension modules under ``directory``."""
    return [p for p in find_compiled_libraries(directory) if is_extension_module(p)]
