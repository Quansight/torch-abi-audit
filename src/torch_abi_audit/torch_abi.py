"""PyTorch Stable ABI classification by symbol inspection.

The PyTorch Stable ABI (introduced in PyTorch 2.9, October 2025) exposes:

* ``aoti_torch_*`` C-shim entry points (``torch/csrc/inductor/aoti_torch/c/shim.h``
  and ``torch/csrc/stable/c/shim.h``).
* ``torch::stable::*`` C++ wrappers in ``torch/csrc/stable/``.
* ``torch::headeronly::*`` libtorch-independent inlined utilities.

Anything else under ``c10::``, ``at::``, ``torch::jit::``, or ``torch::*`` outside
those namespaces is part of the unstable libtorch API. The build-time markers
``TORCH_STABLE_ONLY`` / ``TORCH_TARGET_VERSION`` are not preserved in the binary,
so detection is symbol-based.

Reference: https://docs.pytorch.org/docs/stable/notes/libtorch_stable_abi.html
and ``test/check_binary_symbols.py`` in pytorch/pytorch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# Stable C-shim symbols — both `aoti_torch_*` and the broader `torch_*` C entry
# points (e.g. `torch_call_dispatcher`) are part of the documented stable surface.
# The optional leading underscore matches the Mach-O symbol prefix on macOS.
STABLE_SHIM_RE = re.compile(r"^_?(?:aoti_torch_|torch_)")

# Any C++ symbol referencing one of these unstable namespaces is forbidden.
UNSTABLE_NS_RE = re.compile(r"\b(?:at|c10|torch)::")

SymbolKind = Literal["unstable", "stable_shim", "other"]


def classify_symbol(symbol: str) -> SymbolKind:
    """Classify a single (already-demangled) symbol.

    Returns ``"stable_shim"`` for stable C-shim entry points, ``"unstable"`` for
    references to internal libtorch C++ namespaces, or ``"other"`` for anything
    that isn't part of the libtorch surface at all.
    """
    if STABLE_SHIM_RE.match(symbol):
        return "stable_shim"
    # Strip the stable C++ namespace prefixes before the unstable check so that
    # e.g. ``torch::stable::foo`` does not trip the generic ``torch::`` regex.
    cleaned = symbol.replace("torch::headeronly", "").replace("torch::stable", "")
    if UNSTABLE_NS_RE.search(cleaned):
        return "unstable"
    return "other"


@dataclass(frozen=True, slots=True)
class TorchABIVerdict:
    """Result of PyTorch ABI inspection for a single extension module."""

    uses_torch: bool
    stable: bool
    unstable_symbols: tuple[str, ...] = ()
    stable_shim_count: int = 0


def classify_symbols(symbols: list[str] | tuple[str, ...]) -> TorchABIVerdict:
    """Aggregate per-symbol classifications into a verdict for one extension."""
    unstable: list[str] = []
    stable_shim_count = 0
    for sym in symbols:
        kind = classify_symbol(sym)
        if kind == "unstable":
            unstable.append(sym)
        elif kind == "stable_shim":
            stable_shim_count += 1
    uses_torch = bool(unstable) or stable_shim_count > 0
    stable = uses_torch and not unstable
    return TorchABIVerdict(
        uses_torch=uses_torch,
        stable=stable,
        unstable_symbols=tuple(unstable),
        stable_shim_count=stable_shim_count,
    )
