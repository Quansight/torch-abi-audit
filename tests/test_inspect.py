"""Tests for the inspect.py library splitting (extensions vs bundled_libs)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from torch_abi_audit import inspect_package
from torch_abi_audit.report import PackageReport


def _build_bundled_lib(src_dir: Path, out: Path) -> None:
    """Build a tiny C library WITHOUT PyInit_* — a stand-in for a torch plugin."""
    src = src_dir / "bundled.c"
    src.write_text(
        "int bundled_call(int x) { return x + 1; }\n", encoding="utf-8"
    )
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler found")
    proc = subprocess.run(
        [cc, "-shared", "-fPIC", "-O0", "-o", str(out), str(src)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"compile failed: {proc.stderr.strip()[:200]}")


def test_inspect_package_splits_extensions_and_bundled(
    tmp_path: Path, cpython_unstable_so: Path
) -> None:
    """A directory with one PyInit-bearing .so and one bundled lib should
    produce a one-of-each split."""
    pkg = tmp_path / "fakepkg"
    pkg.mkdir()
    shutil.copy(cpython_unstable_so, pkg / "extension.cpython-311-x86_64-linux-gnu.so")
    _build_bundled_lib(tmp_path, pkg / "libfake.so")

    report: PackageReport = inspect_package(pkg)
    assert len(report.extensions) == 1
    assert len(report.bundled_libs) == 1
    assert report.extensions[0].path.name.startswith("extension.")
    assert report.bundled_libs[0].path.name == "libfake.so"
    # Neither uses torch, so the package roll-up is no-torch even with the
    # bundled lib counted.
    assert report.torch_verdict == "no-torch"
    # CPython verdict only considers extensions; the bundled lib doesn't shift it.
    assert report.cpython_verdict == "not-abi3"


def test_torch_verdict_uses_bundled_libs(tmp_path: Path) -> None:
    """A package whose only torch usage lives in a bundled lib should still
    produce a torch-unstable verdict — that's the whole point of the split.
    Construct the case synthetically so we don't need torch installed."""
    from torch_abi_audit.cpython_abi import CPythonABIVerdict
    from torch_abi_audit.report import ExtensionReport, PackageReport
    from torch_abi_audit.torch_abi import TorchABIVerdict

    benign_ext = ExtensionReport(
        path=Path("/fake/wrapper.cpython-311.so"),
        cpython=CPythonABIVerdict(intent=False, compliant=False),
        torch=TorchABIVerdict(uses_torch=False, stable=False),
    )
    unstable_bundled = ExtensionReport(
        path=Path("/fake/libinternal.so"),
        cpython=CPythonABIVerdict(intent=False, compliant=False),
        torch=TorchABIVerdict(
            uses_torch=True,
            stable=False,
            unstable_symbols=("at::Tensor::numel() const",),
        ),
    )
    pkg = PackageReport(
        name="fake",
        root=Path("/fake"),
        extensions=(benign_ext,),
        bundled_libs=(unstable_bundled,),
    )
    assert pkg.torch_verdict == "torch-unstable"
    # CPython verdict is driven by the extension only — bundled doesn't matter.
    assert pkg.cpython_verdict == "not-abi3"
