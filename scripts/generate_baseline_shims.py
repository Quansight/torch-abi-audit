#!/usr/bin/env python3
"""Generate the vendored list of pre-2.10 (baseline) stable-shim symbols.

PyTorch's ``shim_function_versions.txt`` only lists symbols introduced in 2.10.0
and later; by design a symbol absent from it "was available before 2.10.0". That
rule is safe in-tree (the tree can't reference a symbol newer than itself) but
not for auditing arbitrary wheels: a wheel built against a *future* torch would
reference shims we've never heard of, and "absent from the manifest" would
wrongly read as 2.9.0.

To tell "old" from "too new" we need the fixed set of symbols that actually
existed at 2.9.0. It is immutable (2.9.0 is released), so this is generated once
and vendored as ``data/baseline_shim_symbols.json``. Symbols are extracted from
the stable-shim headers at the ``v2.9.0`` tag with the same declaration regex
PyTorch's ``stable_shim_usage_linter`` uses, then filtered to the
``aoti_torch_*`` / ``torch_*`` function surface (the only names that appear as
linker symbols; the manifest's type/struct entries never do).

Usage::

    python scripts/generate_baseline_shims.py [--ref v2.9.0] [--check]

``--check`` exits non-zero if the vendored copy is stale instead of writing it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from torch_abi_audit import torch_versions

# git ref whose headers define the baseline surface.
# Use a release tag such as v2.9.0; branch names and commit SHAs are unsupported
BASELINE_REF = "v2.9.0"

_RAW_URL = "https://raw.githubusercontent.com/pytorch/pytorch/{ref}/{path}"

# Header set scanned by pytorch's stable_shim_usage_linter. ``stable/c/shim.h``
# postdates 2.9.0 (404 at the tag) and is skipped; the rest are committed.
_SHIM_HEADERS = (
    "torch/csrc/stable/c/shim.h",
    "torch/csrc/inductor/aoti_torch/c/shim.h",
    "torch/csrc/inductor/aoti_torch/c/shim_cpu.h",
    "torch/csrc/inductor/aoti_torch/c/shim_deprecated.h",
    "torch/csrc/inductor/aoti_torch/c/shim_mps.h",
    "torch/csrc/inductor/aoti_torch/c/shim_xpu.h",
    "torch/csrc/inductor/aoti_torch/generated/c_shim_aten.h",
    "torch/csrc/inductor/aoti_torch/generated/c_shim_cpu.h",
    "torch/csrc/inductor/aoti_torch/generated/c_shim_cuda.h",
    "torch/csrc/inductor/aoti_torch/generated/c_shim_mps.h",
    "torch/csrc/inductor/aoti_torch/generated/c_shim_xpu.h",
)

# Upstream's function-declaration matcher (see _stable_shim_utils.py).
_FUNC_RE = re.compile(r"AOTI_TORCH_EXPORT.+?(\w+)\s*\(", re.DOTALL)
# Only names that materialise as linker symbols.
_SHIM_RE = re.compile(r"^(?:aoti_torch_|torch_)")


def _baseline_file_path() -> Path:
    pkg = Path(torch_versions.__file__).resolve().parent
    return pkg / torch_versions._DATA_DIR / torch_versions._BASELINE_FILE


def _fetch(ref: str, path: str) -> str | None:
    """Download one header; ``None`` if it doesn't exist at ``ref`` (404)."""
    try:
        with urllib.request.urlopen(_RAW_URL.format(ref=ref, path=path)) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def collect_symbols(ref: str = BASELINE_REF) -> tuple[set[str], list[str]]:
    """Extract baseline shim symbols from the headers at ``ref``.

    Returns ``(symbols, sources)`` where ``sources`` are the raw URLs of the
    headers that actually existed at ``ref`` (missing ones are skipped).
    """
    symbols: set[str] = set()
    sources: list[str] = []
    for path in _SHIM_HEADERS:
        text = _fetch(ref, path)
        if text is None:
            continue
        sources.append(_RAW_URL.format(ref=ref, path=path))
        for match in _FUNC_RE.finditer(text):
            name = match.group(1)
            if _SHIM_RE.match(name):
                symbols.add(name)
    if not symbols:
        raise RuntimeError(f"no shim symbols extracted from pytorch/pytorch@{ref}")
    return symbols, sources


def _render_payload(
    symbols: set[str], sources: list[str], ref: str, generated: str
) -> str:
    """Serialise to a stable, diff-friendly JSON layout (one symbol per line)."""
    payload = {
        "sources": sources,
        "generator": "scripts/generate_baseline_shims.py",
        "torch_version": ref.lstrip("v"),
        "generated": generated,
        "symbols": sorted(symbols),
    }
    return json.dumps(payload, indent=2)


def _vendored_symbols() -> set[str] | None:
    dest = _baseline_file_path()
    if not dest.exists():
        return None
    return set(json.loads(dest.read_text(encoding="utf-8"))["symbols"])


def is_stale(ref: str = BASELINE_REF) -> bool:
    symbols, _ = collect_symbols(ref)
    return _vendored_symbols() != symbols


def refresh(
    ref: str = BASELINE_REF, *, generated: str | None = None
) -> tuple[Path, bool]:
    symbols, sources = collect_symbols(ref)
    changed = _vendored_symbols() != symbols
    dest = _baseline_file_path()
    if changed:
        today = datetime.datetime.now(tz=datetime.UTC).date()
        stamp = generated or today.isoformat()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            _render_payload(symbols, sources, ref, stamp) + "\n", encoding="utf-8"
        )
    return dest, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref", default=BASELINE_REF, help="git ref on pytorch/pytorch"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the vendored copy is out of date (do not write)",
    )
    args = parser.parse_args(argv)
    dest = _baseline_file_path()

    if args.check:
        if not is_stale(args.ref):
            print(f"up to date ({dest})")
            return 0
        print(f"STALE: {dest} differs from pytorch/pytorch@{args.ref}", file=sys.stderr)
        return 1

    _, changed = refresh(args.ref)
    print(f"{'updated' if changed else 'up to date'} ({dest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
