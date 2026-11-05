"""CPython Stable ABI (PEP 384 / "limited API") classification.

Three signals are checked:

1. **Intent**: the filename carries an ``abi3`` tag (e.g. ``foo.abi3.so``).
2. **Compliance**: every ``Py*`` / ``_Py*`` undefined symbol is part of the
   documented stable symbol set, looked up via the
   `abi3info <https://pypi.org/project/abi3info/>`_ package — the same data
   source ``abi3audit`` uses.
3. **Python dependency** (Windows only, where the dependency list is
   available): a Stable ABI extension must import from the version-agnostic
   ``python3.dll`` forwarder, not from a versioned ``python3XX.dll``. Using only
   stable symbols while linking ``python314.dll`` still pins the wheel to one
   interpreter, so it is not a Stable ABI build.

A module can be **intent-only** (tagged abi3 but using non-stable symbols),
**compliant-only** (uses only stable symbols but isn't tagged), or both.
``abi3audit`` makes the same distinction; we mirror it here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

#: Windows Stable ABI extensions link this forwarder, which re-exports the
#: stable surface for whichever interpreter is installed.
STABLE_PYTHON_DLL = "python3.dll"

#: ``python314.dll``, ``python39.dll``, … but also the free-threaded and debug
#: builds (``python313t.dll``, ``python313_d.dll``), which pin the extension to
#: one interpreter build just as firmly as a plain versioned name does.
_VERSIONED_PYTHON_DLL = re.compile(r"python3\d+[a-z]*(?:_d)?\.dll", re.IGNORECASE)


def _basename(name: str) -> str:
    """Last path component, for dependency names that carry a directory."""
    return re.split(r"[\\/]", name)[-1]


@lru_cache(maxsize=1)
def _stable_symbol_set() -> frozenset[str]:
    """All CPython stable-ABI symbol names (functions + exported data objects)."""
    import abi3info
    return frozenset(s.name for s in abi3info.FUNCTIONS) | frozenset(
        s.name for s in abi3info.DATAS
    )


def _is_python_capi(name: str) -> bool:
    """Heuristic: this symbol references the CPython C API.

    The Mach-O leading underscore has already been stripped by ``symbols.py``,
    so we don't need to handle it here. Some legitimate stable symbols (e.g.
    ``_Py_NoneStruct``) start with one underscore as part of their C name.
    """
    return name.startswith(("Py", "_Py", "PY", "_PY"))


def has_abi3_tag(filename: str) -> bool:
    """True if the extension's filename carries an ``abi3`` tag."""
    # Match the Python ABI tag form: foo.abi3.so / foo.abi3.pyd / foo.abi3.dylib
    return ".abi3." in filename


def imported_python_dll(libraries: Sequence[str] | None) -> str | None:
    """The Python DLL a library imports from, if it imports one at all.

    ``None`` means the dependency list is unavailable (ELF/Mach-O) or the
    library references no Python DLL. Names are matched case-insensitively
    because PE stores them as the linker wrote them.

    A version-pinned dependency wins over the ``python3.dll`` forwarder no
    matter which descriptor comes first: an image that links both is pinned, so
    the answer must not depend on import-table order.
    """
    found: str | None = None
    for name in libraries or ():
        base = _basename(name)
        if base.lower() == STABLE_PYTHON_DLL or _VERSIONED_PYTHON_DLL.fullmatch(base):
            if not is_stable_python_dll(base):
                return name
            found = name
    return found


def is_stable_python_dll(name: str | None) -> bool | None:
    """Whether ``name`` is the version-agnostic forwarder; ``None`` if unknown.

    This is the single source of truth for the rule: callers that render or
    explain a verdict should use it rather than comparing to
    :data:`STABLE_PYTHON_DLL` themselves.
    """
    if name is None:
        return None
    return _basename(name).lower() == STABLE_PYTHON_DLL


@dataclass(frozen=True, slots=True)
class CPythonABIVerdict:
    """Result of CPython Stable ABI inspection for a single extension module.

    ``python_dll`` is the Python DLL the library imports from, when that is
    known: ``python3.dll`` for a Stable ABI build, ``python314.dll`` (or similar)
    for one pinned to a single interpreter version. ``None`` means either no
    Python dependency was found or the platform does not expose the list.
    """

    intent: bool
    compliant: bool
    violations: tuple[str, ...] = ()
    python_dll: str | None = None


def classify_symbols(
    symbols: list[str] | tuple[str, ...],
    filename: str,
    *,
    imported_libraries: Sequence[str] | None = None,
) -> CPythonABIVerdict:
    """Build a verdict from the filename, undefined symbols and dependencies.

    ``imported_libraries`` is the library's dependency list where the platform
    exposes one (PE); omit it elsewhere. When a versioned ``python3XX.dll`` is
    linked, the extension is not Stable ABI even if every symbol it uses is.
    """
    stable = _stable_symbol_set()
    violations: list[str] = []
    saw_capi = False
    for sym in symbols:
        if not _is_python_capi(sym):
            continue
        saw_capi = True
        if sym not in stable:
            violations.append(sym)
    intent = has_abi3_tag(filename)
    python_dll = imported_python_dll(imported_libraries)
    # An extension with no Python C API references at all (rare — e.g. a stub
    # loaded by another mechanism) is trivially compliant; mark it so but the
    # intent flag carries the meaningful signal.
    compliant = saw_capi and not violations
    if is_stable_python_dll(python_dll) is False:
        # Symbol-level checks cannot see this: python3XX.dll carries the same
        # stable names, just for one interpreter version.
        compliant = False
    return CPythonABIVerdict(
        intent=intent,
        compliant=compliant,
        violations=tuple(violations),
        python_dll=python_dll,
    )
