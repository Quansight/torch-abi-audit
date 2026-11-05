"""Unit tests for the CPython ABI classifier — pure logic, no compilation needed."""

from __future__ import annotations

import pytest

from torch_abi_audit.cpython_abi import (
    classify_symbols,
    has_abi3_tag,
    imported_python_dll,
    is_stable_python_dll,
)


def test_abi3_tag_detection():
    assert has_abi3_tag("foo.abi3.so") is True
    assert has_abi3_tag("foo.abi3.pyd") is True
    assert has_abi3_tag("foo.cpython-311-x86_64-linux-gnu.so") is False
    assert has_abi3_tag("foo.cp314-win_amd64.pyd") is False
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


def test_python_dll_detection():
    assert imported_python_dll(["python3.dll", "KERNEL32.dll"]) == "python3.dll"
    assert imported_python_dll(["KERNEL32.dll", "PYTHON314.DLL"]) == "PYTHON314.DLL"
    assert imported_python_dll(["KERNEL32.dll"]) is None
    assert imported_python_dll(None) is None
    # A version-specific dependency must not be mistaken for the forwarder.
    assert imported_python_dll(["python314.dll"]) != "python3.dll"


@pytest.mark.parametrize(
    "name",
    [
        "python314.dll",
        "python39.dll",
        "python313t.dll",  # free-threaded build
        "python313_d.dll",  # debug build
        "python313t_d.dll",  # free-threaded debug build
    ],
)
def test_versioned_python_dll_variants(name: str) -> None:
    """Free-threaded and debug builds pin the extension just as firmly.

    Missing them leaves the pinning check skipped, so such a wheel is reported
    ``abi3-ok`` whenever its symbols happen to be stable.
    """
    assert imported_python_dll([name]) == name
    assert is_stable_python_dll(name) is False
    verdict = classify_symbols(
        ["PyList_New"], f"foo.abi3{name}", imported_libraries=[name]
    )
    assert verdict.compliant is False


@pytest.mark.parametrize(
    "libraries",
    [
        ["python3.dll", "python314.dll"],
        ["python314.dll", "python3.dll"],
    ],
)
def test_versioned_dll_wins_regardless_of_order(libraries: list[str]) -> None:
    """An image linking both is pinned; the verdict must not depend on order."""
    assert imported_python_dll(libraries) == "python314.dll"
    verdict = classify_symbols(
        ["PyList_New"], "foo.abi3.pyd", imported_libraries=libraries
    )
    assert verdict.compliant is False


def test_dependency_names_with_a_path_are_handled() -> None:
    """dumpbin's dependency regex accepts a path, so the rule must strip it."""
    assert is_stable_python_dll(r"C:\Windows\System32\python3.dll") is True
    assert is_stable_python_dll("C:/Windows/System32/python3.dll") is True
    assert imported_python_dll([r"C:\x\python314.dll"]) == r"C:\x\python314.dll"


def test_is_stable_python_dll():
    assert is_stable_python_dll("python3.dll") is True
    assert is_stable_python_dll("PYTHON3.DLL") is True
    assert is_stable_python_dll("python314.dll") is False
    assert is_stable_python_dll(None) is None


def test_versioned_python_dll_breaks_compliance():
    """Stable symbols alone are not a Windows Stable ABI build.

    ``python314.dll`` exports the same stable names, so symbol inspection alone
    cannot tell the two apart — the dependency list can.
    """
    stable_symbols = ["PyList_New", "PyLong_FromLong"]

    forwarder = classify_symbols(
        stable_symbols, "foo.abi3.pyd", imported_libraries=["python3.dll"]
    )
    pinned = classify_symbols(
        stable_symbols, "foo.abi3.pyd", imported_libraries=["python314.dll"]
    )

    assert forwarder.compliant is True
    assert forwarder.python_dll == "python3.dll"
    assert pinned.compliant is False
    assert pinned.python_dll == "python314.dll"
    # The symbol-level verdict is unchanged; only the dependency differs.
    assert pinned.violations == ()


def test_dependency_list_is_optional():
    """ELF/Mach-O pass no dependency list, and behaviour must not change."""
    v = classify_symbols(["PyList_New"], filename="foo.abi3.so")
    assert v.compliant is True
    assert v.python_dll is None
