"""Tests for the demangler wrapper."""

from __future__ import annotations

from torch_abi_audit.demangle import demangle_symbol


def test_passes_through_c_symbols():
    assert demangle_symbol("PyList_New") == "PyList_New"
    assert demangle_symbol("aoti_torch_get_dim") == "aoti_torch_get_dim"
    assert demangle_symbol("memcpy") == "memcpy"


def test_demangles_itanium_mangled_name():
    # _Z3fooi → foo(int) per the Itanium ABI.
    assert demangle_symbol("_Z3fooi") == "foo(int)"


def test_preserves_glibcxx_version_suffix():
    # The GNU symbol-versioning suffix is split off before demangling and
    # re-attached afterwards, since pycxxfilt rejects it as invalid input.
    assert (
        demangle_symbol("_Z3fooi@GLIBCXX_3.4")
        == "foo(int)@GLIBCXX_3.4"
    )


def test_unrecognised_mangled_name_falls_back_to_input():
    junk = "_Znotmangled"
    assert demangle_symbol(junk) == junk
