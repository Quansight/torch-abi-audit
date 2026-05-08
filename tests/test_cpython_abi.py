"""Unit tests for the CPython ABI classifier — pure logic, no compilation needed."""

from __future__ import annotations

from torch_abi_audit.cpython_abi import classify_symbols, has_abi3_tag


def test_abi3_tag_detection():
    assert has_abi3_tag("foo.abi3.so") is True
    assert has_abi3_tag("foo.abi3.pyd") is True
    assert has_abi3_tag("foo.cpython-311-x86_64-linux-gnu.so") is False
    assert has_abi3_tag("foo.so") is False


def test_compliant_only_stable_symbols():
    v = classify_symbols(
        ["PyList_New", "PyLong_FromLong", "Py_BuildValue"],
        filename="foo.abi3.so",
    )
    assert v.intent is True
    assert v.compliant is True
    assert v.violations == ()


def test_violations_from_private_symbols():
    v = classify_symbols(
        ["PyList_New", "_PyArg_CheckPositional"],
        filename="foo.abi3.so",
    )
    assert v.intent is True
    assert v.compliant is False
    assert "_PyArg_CheckPositional" in v.violations


def test_no_intent_no_capi():
    v = classify_symbols(["memcpy", "fopen"], filename="foo.so")
    assert v.intent is False
    assert v.compliant is False  # no Python C API at all → not compliant in our model
    assert v.violations == ()


def test_known_stable_data_symbol():
    """`_Py_NoneStruct` is in stable_abi.toml's [data] section."""
    v = classify_symbols(["_Py_NoneStruct", "PyList_New"], filename="foo.abi3.so")
    assert v.compliant is True
    assert v.violations == ()
