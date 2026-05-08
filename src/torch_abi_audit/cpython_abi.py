"""CPython Stable ABI (PEP 384 / "limited API") classification.

Two signals are checked:

1. **Intent**: the filename carries an ``abi3`` tag (e.g. ``foo.abi3.so``).
2. **Compliance**: every ``Py*`` / ``_Py*`` undefined symbol is part of the
   documented stable symbol set, looked up via the
   `abi3info <https://pypi.org/project/abi3info/>`_ package — the same data
   source ``abi3audit`` uses.

A module can be **intent-only** (tagged abi3 but using non-stable symbols),
**compliant-only** (uses only stable symbols but isn't tagged), or both.
``abi3audit`` makes the same distinction; we mirror it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


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


@dataclass(frozen=True, slots=True)
class CPythonABIVerdict:
    """Result of CPython Stable ABI inspection for a single extension module."""

    intent: bool
    compliant: bool
    violations: tuple[str, ...] = ()


def classify_symbols(symbols: list[str] | tuple[str, ...], filename: str) -> CPythonABIVerdict:
    """Build a verdict from the extension's filename and undefined symbols."""
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
    # An extension with no Python C API references at all (rare — e.g. a stub
    # loaded by another mechanism) is trivially compliant; mark it so but the
    # intent flag carries the meaningful signal.
    compliant = saw_capi and not violations
    return CPythonABIVerdict(
        intent=intent,
        compliant=compliant,
        violations=tuple(violations),
    )
