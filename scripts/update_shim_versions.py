#!/usr/bin/env python3
"""Regenerate the vendored PyTorch stable-shim version table.

Downloads PyTorch's ``torch/csrc/stable/c/shim_function_versions.txt``, parses
it, and writes it pre-parsed to ``torch_abi_audit/data/shim_function_versions.json``.
The library only reads that JSON; all update logic lives here.

Usage::

    python scripts/update_shim_versions.py [--ref REF] [--check]

``--check`` exits non-zero if the vendored copy is stale instead of writing it.
Staleness compares symbols only, ignoring the ``generated`` date.
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
from torch_abi_audit.torch_versions import format_version

# ``{ref}`` is a git ref on pytorch/pytorch.
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/pytorch/pytorch/{ref}"
    "/torch/csrc/stable/c/shim_function_versions.txt"
)

# Upstream lines read ``function_name: TORCH_VERSION_MAJOR_MINOR_PATCH``.
_VERSION_RE = re.compile(r"TORCH_VERSION_(\d+)_(\d+)_(\d+)")


def _data_file_path() -> Path:
    """Vendored JSON inside the installed package (what the library reads)."""
    pkg = Path(torch_versions.__file__).resolve().parent
    return pkg / torch_versions._DATA_DIR / torch_versions._MANIFEST_FILE


def _parse_manifest(text: str) -> dict[str, tuple[int, int, int]]:
    """Parse upstream ``shim_function_versions.txt`` into ``{symbol: version}``."""
    table: dict[str, tuple[int, int, int]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition(":")
        if not sep:
            continue
        m = _VERSION_RE.search(version)
        if m:
            table[name.strip()] = (int(m[1]), int(m[2]), int(m[3]))
    return table


def _render_payload(
    table: dict[str, tuple[int, int, int]], source: str, generated: str
) -> str:
    """Serialise to JSON with sorted, one-per-line symbols for reviewable diffs."""
    payload = {
        "sources": [source],
        "generator": "scripts/update_shim_versions.py",
        "generated": generated,
        "symbols": {name: format_version(table[name]) for name in sorted(table)},
    }
    return json.dumps(payload, indent=2)


def _fetch_manifest(ref: str) -> tuple[str, dict[str, tuple[int, int, int]]]:
    """Download the upstream manifest; return ``(source_url, parsed table)``."""
    url = UPSTREAM_URL.format(ref=ref)
    try:
        with urllib.request.urlopen(url) as resp:
            upstream = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
    return url, _parse_manifest(upstream)


def _vendored_symbols() -> dict[str, str] | None:
    """Currently vendored symbol map, or ``None`` if the file is missing."""
    dest = _data_file_path()
    if not dest.exists():
        return None
    return json.loads(dest.read_text(encoding="utf-8"))["symbols"]


def is_stale(ref: str = "main") -> bool:
    """True if the vendored symbol table differs from pytorch/pytorch@``ref``."""
    _, table = _fetch_manifest(ref)
    upstream = {name: format_version(table[name]) for name in sorted(table)}
    return _vendored_symbols() != upstream


def refresh(ref: str = "main", *, generated: str | None = None) -> tuple[Path, bool]:
    """Regenerate the vendored table from pytorch/pytorch@``ref``.

    Returns ``(path, changed)``; rewrites (bumping ``generated``) only when the
    symbol table actually changed.
    """
    url, table = _fetch_manifest(ref)
    new_symbols = {name: format_version(table[name]) for name in sorted(table)}
    changed = _vendored_symbols() != new_symbols
    dest = _data_file_path()
    if changed:
        today = datetime.datetime.now(tz=datetime.UTC).date()
        stamp = generated or today.isoformat()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_render_payload(table, url, stamp) + "\n", encoding="utf-8")
    return dest, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        default="main",
        help="git release tag or branch on pytorch/pytorch",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the vendored copy is out of date (do not write)",
    )
    args = parser.parse_args(argv)

    dest = _data_file_path()

    try:
        if args.check:
            if not is_stale(args.ref):
                print(f"up to date ({dest})")
                return 0
            print(
                f"STALE: {dest} differs from pytorch/pytorch@{args.ref}; "
                "run scripts/update_shim_versions.py",
                file=sys.stderr,
            )
            return 1

        _, changed = refresh(args.ref)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if changed:
        print(f"updated {dest} from pytorch/pytorch@{args.ref}")
    else:
        print(f"up to date ({dest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
