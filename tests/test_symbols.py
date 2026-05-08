"""Symbol extraction tests — these need a compiler and use the on-demand fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from torch_abi_audit.symbols import (
    extract_undefined_symbols,
    has_pyinit_symbol,
    is_extension_module,
)


def test_pyinit_symbol_present(cpython_stable_so: Path):
    assert has_pyinit_symbol(cpython_stable_so) is True


def test_is_extension_module_abi3_filename(cpython_stable_so: Path):
    assert is_extension_module(cpython_stable_so) is True


def test_is_extension_module_untagged(cpython_unstable_so: Path):
    """An untagged .so still counts as an extension if PyInit_* is defined."""
    assert is_extension_module(cpython_unstable_so) is True


def test_abi3_filename_without_pyinit_is_not_an_extension(tmp_path: Path):
    """torchaudio's STABLE_TORCH_LIBRARY plugins use ``.abi3.so`` filenames but
    have no ``PyInit_*`` — they're loaded by torch, not by Python's importer.
    The classifier must not treat them as extensions.
    """
    fake = tmp_path / "_loadable.abi3.so"
    fake.write_bytes(b"\x7fELF" + b"\x00" * 60)  # not actually a valid ELF; nm will refuse
    assert is_extension_module(fake) is False


def test_extract_undefined_symbols_smoke(cpython_stable_so: Path):
    syms = extract_undefined_symbols(cpython_stable_so)
    assert any(s.startswith("PyModule_Create") for s in syms)


def test_extract_undefined_symbols_strips_macos_prefix(cpython_stable_so: Path):
    """Whatever platform we're on, the returned symbols should not have an
    extra leading underscore for known C API names like ``PyModule_Create2``."""
    syms = extract_undefined_symbols(cpython_stable_so)
    bad = [s for s in syms if s.startswith("__Py") or s.startswith("__PY")]
    # Known stable data symbols look like "_Py_NoneStruct" with exactly one
    # underscore. Anything starting with two is a Mach-O artifact we failed to strip.
    assert bad == [], f"unstripped Mach-O underscores: {bad[:5]}"
