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


# ---------------------------------------------------------------------------
# --check policy


def _pkg(name, *, torch_stable=None, cpython_compliant=None):
    """Build a PackageReport whose verdicts match the requested policy state.

    ``torch_stable`` None -> no torch use; True/False -> stable/unstable.
    ``cpython_compliant`` None -> no extensions; True/False -> abi3 or not.
    """
    if torch_stable is None:
        torch = TorchABIVerdict(uses_torch=False, stable=False)
    else:
        torch = TorchABIVerdict(uses_torch=True, stable=torch_stable)
    exts = ()
    if cpython_compliant is not None:
        exts = (
            ExtensionReport(
                path=Path(f"/env/{name}/_c.so"),
                cpython=CPythonABIVerdict(
                    intent=cpython_compliant, compliant=cpython_compliant
                ),
                torch=torch,
            ),
        )
    return PackageReport(name, Path(f"/env/{name}"), extensions=exts)


def test_check_torch_flags_unstable_only():
    from torch_abi_audit.report import CheckPolicy, collect_violations

    pkgs = [
        _pkg("unstable", torch_stable=False, cpython_compliant=True),
        _pkg("stable", torch_stable=True, cpython_compliant=True),
        _pkg("notorch", cpython_compliant=True),
    ]
    v = collect_violations(pkgs, CheckPolicy.TORCH)
    assert [name for name, _ in v] == ["unstable"]


def test_check_abi3_scoped_to_torch_users():
    from torch_abi_audit.report import CheckPolicy, collect_violations

    pkgs = [
        _pkg("torch_no_abi3", torch_stable=True, cpython_compliant=False),
        _pkg("notorch_no_abi3", cpython_compliant=False),  # ignored: no torch
    ]
    v = collect_violations(pkgs, CheckPolicy.ABI3)
    assert [name for name, _ in v] == ["torch_no_abi3"]


def test_check_both_unions_reasons():
    from torch_abi_audit.report import CheckPolicy, collect_violations

    pkgs = [_pkg("bad", torch_stable=False, cpython_compliant=False)]
    v = collect_violations(pkgs, CheckPolicy.BOTH)
    assert len(v) == 1
    name, reasons = v[0]
    assert name == "bad"
    assert len(reasons) == 2
