"""CLI smoke tests."""

from __future__ import annotations

import json

import pytest

from torch_abi_audit.cli import main


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "torch-abi-audit" in out


def test_no_target_errors(capsys: pytest.CaptureFixture[str]):
    rc = main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "TARGET" in err or "--env" in err


def test_inspect_stdlib_module_json(capsys: pytest.CaptureFixture[str]):
    """`json` is a pure-Python stdlib module — should produce a clean report with no extensions."""
    rc = main(["json", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["name"] == "json"
    assert payload["extensions"] == []


def test_inspect_extension_module(
    cpython_unstable_so, capsys: pytest.CaptureFixture[str]
):
    """Inspect a freshly-built non-abi3 extension by path; should report no torch use."""
    rc = main([str(cpython_unstable_so), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["extensions"]) == 1
    ext = payload["extensions"][0]
    assert ext["torch"]["uses_torch"] is False
    assert ext["cpython"]["intent"] is False


def test_inspect_abi3_fixture_is_compliant(
    cpython_stable_so, capsys: pytest.CaptureFixture[str]
):
    """The Py_LIMITED_API fixture should be detected as abi3-compliant."""
    rc = main([str(cpython_stable_so), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    ext = payload["extensions"][0]
    assert ext["cpython"]["intent"] is True
    assert ext["cpython"]["compliant"] is True
    assert ext["cpython"]["violations"] == []
