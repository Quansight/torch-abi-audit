#!/usr/bin/env python3
"""Local real-world smoke test for torch-abi-audit.

Spins up a temporary uv-managed venv, installs PyTorch and a handful of
ecosystem packages, then verifies the tool's verdicts match expectations.

Usage::

    python scripts/check_real_world.py [--keep] [--report PATH]

Linux only. Requires ``uv`` on PATH. The install is heavy (torch alone is
roughly 2 GB) and runs against the public PyPI index.

Output columns:
    EXPECTED / ACTUAL  -- ``torch_verdict`` from the tool.
    EXTS               -- Python extension modules (``PyInit_*`` defined).
    BUNDLED            -- other compiled .so files shipped in the package
                          (e.g. torch/lib/libtorch_python.so, libtorchcodec_core*.so);
                          loaded via dlopen / STABLE_TORCH_LIBRARY rather than
                          Python's importer. The verdict considers both lists.
    STABLE / UNSTABLE  -- counts of libs (extensions + bundled) classified each way.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Each entry is `package -> expected torch_verdict`.
# Update when a package's stable-ABI status changes upstream.
EXPECTED: dict[str, str] = {
    "torchaudio": "torch-stable",       # migration completed in 2.10 (pytorch/audio#3902)
    "torch": "torch-unstable",          # implements libtorch; references at::/c10:: by design
    "torchcodec": "torch-unstable",     # not yet migrated to torch::stable
}

# Runs inside the freshly-built test venv. Uses the Python API directly so we
# can read the @property roll-ups that the JSON formatter doesn't include.
INNER = r"""
import json, sys
from importlib.metadata import PackageNotFoundError, version
from torch_abi_audit import inspect_package

out = {}
for name in sys.argv[1:]:
    r = inspect_package(name)
    libs = (*r.extensions, *r.bundled_libs)
    try:
        ver = version(name)
    except PackageNotFoundError:
        ver = "?"
    out[name] = {
        "version": ver,
        "torch_verdict": r.torch_verdict,
        "cpython_verdict": r.cpython_verdict,
        "n_extensions": len(r.extensions),
        "n_bundled_libs": len(r.bundled_libs),
        "n_unstable_libs": sum(
            1 for e in libs if e.torch.uses_torch and not e.torch.stable
        ),
        "n_stable_libs": sum(1 for e in libs if e.torch.stable),
        "sample_unstable_symbols": sorted({
            sym for e in libs for sym in e.torch.unstable_symbols
        })[:10],
        "error": r.error,
    }
print(json.dumps(out))
"""


def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, capture_output=capture, text=True, check=False)


def _die(msg: str, code: int = 2) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return code


def _setup_venv(venv: Path) -> int:
    if shutil.which("uv") is None:
        return _die("uv not found on PATH")
    rc = _run(["uv", "venv", "--python", "3.11", str(venv)]).returncode
    if rc != 0:
        return _die(f"uv venv failed (exit {rc})")
    return 0


def _install(venv: Path, repo: Path) -> int:
    py = str(venv / "bin" / "python")
    proc = _run(
        [
            "uv", "pip", "install",
            "--python", py,
            *EXPECTED.keys(),
            "-e", str(repo),
        ],
        capture=True,
    )
    if proc.returncode != 0:
        # The install can take many minutes; surface tails of both streams so
        # the user doesn't have to scroll through everything to see the error.
        print(proc.stdout, end="")
        print(proc.stderr, end="", file=sys.stderr)
        return _die(f"uv pip install failed (exit {proc.returncode})")
    return 0


def _inspect(venv: Path) -> dict[str, dict[str, object]] | None:
    py = str(venv / "bin" / "python")
    proc = _run([py, "-c", INNER, *EXPECTED.keys()], capture=True)
    if proc.returncode != 0:
        print(proc.stdout, end="")
        print(proc.stderr, end="", file=sys.stderr)
        return None
    return json.loads(proc.stdout)


def _print_table(report: dict[str, dict[str, object]]) -> bool:
    name_w = max(len(n) for n in EXPECTED)
    ver_w = max(8, max(len(str(report.get(p, {}).get("version", "?"))) for p in EXPECTED))
    print()
    header = (
        f"  {'PACKAGE':<{name_w}}  {'VERSION':<{ver_w}}  "
        f"{'EXPECTED':<16}  {'ACTUAL':<16}  "
        f"EXTS  BUNDLED  STABLE  UNSTABLE"
    )
    print(header)
    print(
        f"  {'-' * name_w}  {'-' * ver_w}  {'-' * 16}  {'-' * 16}  "
        f"----  -------  ------  --------"
    )
    all_ok = True
    for pkg, expected in EXPECTED.items():
        row = report.get(pkg, {})
        version = str(row.get("version", "?"))
        actual = str(row.get("torch_verdict", "missing"))
        mark = "PASS" if actual == expected else "FAIL"
        if actual != expected:
            all_ok = False
        n_ext = row.get("n_extensions", 0)
        n_bundled = row.get("n_bundled_libs", 0)
        n_stable = row.get("n_stable_libs", 0)
        n_unstable = row.get("n_unstable_libs", 0)
        print(
            f"  {pkg:<{name_w}}  {version:<{ver_w}}  "
            f"{expected:<16}  {actual:<16}  "
            f"{n_ext:>4}  {n_bundled:>7}  {n_stable:>6}  {n_unstable:>8}  {mark}"
        )
        if row.get("error"):
            print(f"      error: {row['error']}")
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true",
                    help="don't delete the temp venv on exit")
    ap.add_argument("--report", metavar="PATH", type=Path,
                    help="write the full inner-JSON report to PATH")
    args = ap.parse_args()

    if sys.platform != "linux":
        return _die(f"only Linux is supported (got {sys.platform})")

    repo = Path(__file__).resolve().parent.parent
    venv = Path(tempfile.mkdtemp(prefix="ctsabi-rw-"))
    print(f"venv: {venv}")
    cleanup = not args.keep

    try:
        rc = _setup_venv(venv)
        if rc:
            return rc
        rc = _install(venv, repo)
        if rc:
            return rc
        report = _inspect(venv)
        if report is None:
            return _die("inspection subprocess failed", code=2)
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"wrote full report to {args.report}")
        all_ok = _print_table(report)
        return 0 if all_ok else 1
    finally:
        if cleanup:
            shutil.rmtree(venv, ignore_errors=True)
        else:
            print(f"venv kept at {venv}")


if __name__ == "__main__":
    sys.exit(main())
