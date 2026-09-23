"""Map PyTorch stable-ABI shim symbols to the torch version that introduced them.

Two vendored JSON files back this module, both regenerated from pytorch/pytorch:

* ``data/shim_function_versions.json`` -- PyTorch's manifest of shim symbols
  introduced in 2.10.0 and later, as ``{symbol: "major.minor.patch"}``
  (``scripts/update_shim_versions.py``).
* ``data/baseline_shim_symbols.json`` -- the fixed set of shim symbols that
  already existed at the torch release named in its ``torch_version`` field
  (2.9.0, when the stable ABI shipped), as a plain symbol list
  (``scripts/generate_baseline_shims.py``).

The manifest lists only 2.10.0+ symbols, so on its own "absent" is ambiguous:
in-tree it means "pre-2.10.0", but for arbitrary wheels it could mean "newer
than our data". The baseline file resolves that. A shim symbol is *versioned*
(in the manifest, 2.10.0+), *baseline* (in the 2.9.0 set), or *unknown* (in
neither -- newer than our data). :func:`minimum_version` floors a binary at the
max introduction version across the shims it references; :func:`stable_shim_versions`
exposes the merged ``{symbol: (major, minor, patch)}`` map.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

#: Floor for any stable shim symbol; mirrors the baseline file's ``torch_version``.
BASELINE_VERSION: tuple[int, int, int] = (2, 9, 0)

_DATA_DIR = "data"
_MANIFEST_FILE = "shim_function_versions.json"
_BASELINE_FILE = "baseline_shim_symbols.json"

Version = tuple[int, int, int]


@lru_cache
def parse_version(text: str) -> Version:
    """Parse a ``"2.10.0"`` string into a ``(2, 10, 0)`` tuple."""
    try:
        major, minor, patch = text.strip().split(".")
        return (int(major), int(minor), int(patch))
    except ValueError:
        raise ValueError(f"unrecognised version string: {text!r}") from None


def format_version(version: Version) -> str:
    """Render a ``(2, 10, 0)`` tuple as ``"2.10.0"``."""
    return ".".join(str(p) for p in version)


def _load(name: str) -> dict:
    anchor = __package__ or "torch_abi_audit"  # __package__ is str | None
    raw = files(anchor).joinpath(_DATA_DIR, name).read_text(encoding="utf-8")
    return json.loads(raw)


@lru_cache(maxsize=1)
def _manifest_table() -> dict[str, Version]:
    """The 2.10.0+ manifest as ``{symbol: version}`` (excludes baseline shims)."""
    symbols: dict[str, str] = _load(_MANIFEST_FILE)["symbols"]
    return {name: parse_version(v) for name, v in symbols.items()}


@lru_cache(maxsize=1)
def _baseline_symbols() -> frozenset[str]:
    """The fixed set of shim symbols that existed at 2.9.0."""
    return frozenset(_load(_BASELINE_FILE)["symbols"])


@lru_cache(maxsize=1)
def _version_table() -> dict[str, Version]:
    # Baseline symbols take the baseline file's torch_version; manifest symbols
    # take their listed version and win on any overlap (currently empty).
    baseline = _load(_BASELINE_FILE)
    baseline_version = parse_version(baseline["torch_version"])
    table: dict[str, Version] = {sym: baseline_version for sym in baseline["symbols"]}
    table.update(_manifest_table())
    return table


def stable_shim_versions() -> dict[str, Version]:
    """Map each shim function to the torch version that introduced it into the stable ABI.

    Returns a fresh dict; symbols in neither vendored file are absent.
    """
    return dict(_version_table())


def _normalise(symbol: str) -> str:
    """Strip a single leading underscore (the Mach-O symbol prefix) for lookups."""
    return symbol.removeprefix("_")


def symbol_version(symbol: str) -> Version | None:
    """Introducing torch version for ``symbol``, or ``None`` if unlisted (pre-2.10.0)."""
    return _manifest_table().get(_normalise(symbol))


def minimum_version(
    shim_symbols: list[str] | tuple[str, ...],
) -> tuple[Version | None, tuple[str, ...], tuple[str, ...]]:
    """Minimum torch version for pre-classified stable shim symbols.

    Returns ``(version, defining, unknown)``:

    * ``version`` -- the max introduction version across known symbols, or
      ``None`` if no shim symbols were given. Any shim symbol implies at least
      :data:`BASELINE_VERSION`.
    * ``defining`` -- the manifest symbols pinning ``version`` (empty at the
      2.9.0 baseline floor, which no single symbol introduces).
    * ``unknown`` -- shim symbols in neither the 2.10.0+ manifest nor the 2.9.0
      baseline set: newer than our vendored data. Surfaced so they are not
      silently floored at 2.9.0; regenerate the data files to resolve them.
    """
    if not shim_symbols:
        return None, (), ()
    table = _manifest_table()
    baseline = _baseline_symbols()
    best = BASELINE_VERSION
    unknown: list[str] = []
    for sym in shim_symbols:
        name = _normalise(sym)
        version = table.get(name)
        if version is not None:
            best = max(best, version)
        elif name not in baseline:
            unknown.append(sym)
    defining = tuple(
        sorted({s for s in shim_symbols if table.get(_normalise(s)) == best})
    )
    return best, defining, tuple(sorted(set(unknown)))
