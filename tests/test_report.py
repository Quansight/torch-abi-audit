"""Tests for report.py — focused on the per-row label logic."""

from __future__ import annotations

from pathlib import Path

from torch_abi_audit.cpython_abi import CPythonABIVerdict
from torch_abi_audit.report import ExtensionReport, PackageReport, _cpython_label
from torch_abi_audit.torch_abi import TorchABIVerdict


def test_env_verbose_expands_stable_packages():
    """`--env -v` must expand stable packages so their version-defining symbols
    show, not only unstable/error ones (PR #4 #4)."""
    from torch_abi_audit.report import EnvironmentReport, format_environment_table

    stable_ext = ExtensionReport(
        path=Path("/env/mypkg/_c.abi3.so"),
        cpython=CPythonABIVerdict(intent=True, compliant=True),
        torch=TorchABIVerdict(
            uses_torch=True,
            stable=True,
            stable_shim_count=1,
            min_torch_version="2.14.0",
            version_defining_symbols=("torch_has_storage",),
        ),
    )
    pkg = PackageReport("mypkg", Path("/env/mypkg"), extensions=(stable_ext,))
    env = EnvironmentReport(site_packages=Path("/env"), packages=(pkg,))
    out = format_environment_table(env, verbose=True)
    assert "requires torch 2.14.0: torch_has_storage" in out


def test_label_compliant():
    assert _cpython_label(CPythonABIVerdict(intent=True, compliant=True)) == "abi3-ok"
    assert _cpython_label(CPythonABIVerdict(intent=False, compliant=True)) == "abi3-ok"


def test_label_intent_tagged_with_actual_violations():
    v = CPythonABIVerdict(
        intent=True, compliant=False, violations=("_PyArg_CheckPositional",)
    )
    assert _cpython_label(v) == "abi3-tagged-violations"


def test_label_intent_tagged_no_capi_at_all():
    """A torch plugin like ``_torchaudio.abi3.so``: filename says abi3 but the
    file references no Python C API symbols. Must NOT be labelled "violations"
    when there are zero actual violations.
    """
    v = CPythonABIVerdict(intent=True, compliant=False, violations=())
    assert _cpython_label(v) == "abi3-tagged-no-capi"


def test_label_no_intent_with_violations():
    v = CPythonABIVerdict(
        intent=False, compliant=False, violations=("_PyArg_BadArgument",)
    )
    assert _cpython_label(v) == "uses-private-api"


def test_label_no_intent_no_capi():
    v = CPythonABIVerdict(intent=False, compliant=False, violations=())
    assert _cpython_label(v) == "not-abi3"
