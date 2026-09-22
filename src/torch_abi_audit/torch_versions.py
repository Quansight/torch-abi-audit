"""Vendored PyTorch stable-shim symbol -> introducing-torch-version data.

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
than our data". The baseline file resolves the pre-2.10.0 half. :func:`stable_shim_versions`
merges both into one ``{symbol: (major, minor, patch)}`` map; symbols in neither
are simply absent from it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

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
def _version_table() -> dict[str, Version]:
    # Baseline symbols take the baseline file's torch_version; manifest symbols
    # take their listed version and win on any overlap (currently empty).
    baseline = _load(_BASELINE_FILE)
    manifest = _load(_MANIFEST_FILE)
    baseline_version = parse_version(baseline["torch_version"])
    table: dict[str, Version] = {sym: baseline_version for sym in baseline["symbols"]}
    table.update((sym, parse_version(v)) for sym, v in manifest["symbols"].items())
    return table


def stable_shim_versions() -> dict[str, Version]:
    """Map each shim function to the torch version that introduced it into the stable ABI.

    Returns a fresh dict; symbols in neither vendored file are absent.
    """
    return dict(_version_table())
