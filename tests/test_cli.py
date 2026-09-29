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


def test_check_passes_on_no_torch_target(capsys: pytest.CaptureFixture[str]):
    """`--check torch` on a pure-Python target exits 0."""
    rc = main(["json", "--check", "torch"])
    assert rc == 0


def test_check_torch_fails_on_unstable(monkeypatch, capsys: pytest.CaptureFixture[str]):
    from pathlib import Path

    from torch_abi_audit import cli
    from torch_abi_audit.cpython_abi import CPythonABIVerdict
    from torch_abi_audit.report import ExtensionReport, PackageReport
    from torch_abi_audit.torch_abi import TorchABIVerdict

    unstable = PackageReport(
        "evilpkg",
        Path("/x/evilpkg"),
        extensions=(
            ExtensionReport(
                path=Path("/x/evilpkg/_c.so"),
                cpython=CPythonABIVerdict(intent=False, compliant=True),
                torch=TorchABIVerdict(uses_torch=True, stable=False),
            ),
        ),
    )
    monkeypatch.setattr(cli, "inspect_package", lambda t: unstable)
    rc = main(["evilpkg", "--check", "torch"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL" in err and "evilpkg" in err


def test_check_operational_error_wins_over_policy(monkeypatch):
    from torch_abi_audit import cli

    def boom(t):
        raise RuntimeError("nope")

    monkeypatch.setattr(cli, "inspect_package", boom)
    rc = main(["missing", "--check", "torch"])
    assert rc == 2
