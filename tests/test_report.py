"""Tests for report.py — focused on the per-row label logic."""

from __future__ import annotations

from torch_abi_audit.cpython_abi import CPythonABIVerdict
from torch_abi_audit.report import _cpython_label


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
