"""Symbol extraction tests, with compiled fixtures and mocked nm output."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from torch_abi_audit import inspect_package
from torch_abi_audit.symbols import (
    extract_undefined_symbols,
    has_module_entrypoint,
    is_extension_module,
    is_module_entrypoint,
)


def test_pyinit_symbol_present(cpython_stable_so: Path):
    assert has_module_entrypoint(cpython_stable_so) is True


@pytest.mark.parametrize(
    "name",
    [
        "PyInit_foo",
        "PyInitU_foo",
        "PyModExport_foo",  # PEP 793
        "PyModExportU_foo",  # PEP 793 non-ASCII
        "_PyModExport_foo",  # Mach-O leading underscore
    ],
)
def test_is_module_entrypoint_accepts(name: str):
    assert is_module_entrypoint(name) is True


@pytest.mark.parametrize(
    "name",
    ["PyModule_Create2", "PyInit", "not_an_entrypoint", "PyModExport", "Py_Initialize"],
)
def test_is_module_entrypoint_rejects(name: str):
    assert is_module_entrypoint(name) is False


@pytest.mark.parametrize("prefix", ["PyModExport_", "PyModExportU_"])
@pytest.mark.parametrize("defined", [True, False])
def test_pymodexport_package_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    defined: bool,
):
    """Only a defined export hook makes a library a Python extension."""
    library = tmp_path / "example.so"
    library.touch()
    symbol = f"{prefix}example"

    def fake_nm(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        # Undefined-symbol extraction and entry-point detection use separate
        # nm invocations.
        if args[1].startswith("-uj"):
            output = "" if defined else f"{symbol}\n"
        else:
            output = (
                f"0000000000001000 T {symbol}\n"
                if defined
                else f"                 U {symbol}\n"
            )
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(
        "torch_abi_audit.symbols.shutil.which", lambda _: "/usr/bin/nm"
    )
    monkeypatch.setattr("torch_abi_audit.symbols.subprocess.run", fake_nm)

    report = inspect_package(tmp_path)

    assert len(report.extensions) == int(defined)
    assert len(report.bundled_libs) == int(not defined)


def test_compiled_pymodexport_package_classification(cpython_pymodexport_so: Path):
    """A real export-only module is importable and classified as an extension."""
    spec = importlib.util.spec_from_file_location(
        "fixture_pymodexport", cpython_pymodexport_so
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.__name__ == "fixture_pymodexport"

    report = inspect_package(cpython_pymodexport_so.parent)

    assert report.error is None
    assert [ext.path for ext in report.extensions] == [cpython_pymodexport_so]
    assert report.extensions[0].error is None
    assert report.bundled_libs == ()


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
