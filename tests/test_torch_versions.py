"""Tests for torch_abi_audit.torch_versions (stable_shim_versions and helpers)."""

from __future__ import annotations

import pytest

from torch_abi_audit import torch_versions
from torch_abi_audit.torch_versions import (
    format_version,
    parse_version,
    stable_shim_versions,
)

_load = torch_versions._load


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2.10.0", (2, 10, 0)), ("2.9.0", (2, 9, 0)), (" 3.0.1 ", (3, 0, 1))],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("bad", ["2.10", "2.x.0", "", "2.10.0.1"])
def test_parse_version_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


def test_format_version_roundtrips():
    assert format_version(parse_version("2.14.0")) == "2.14.0"


def test_version_table_merges_baseline_and_manifest():
    baseline = _load(torch_versions._BASELINE_FILE)
    manifest = _load(torch_versions._MANIFEST_FILE)
    table = stable_shim_versions()

    assert set(table) == set(baseline["symbols"]) | set(manifest["symbols"])


def test_version_table_baseline_uses_torch_version_field():
    baseline = _load(torch_versions._BASELINE_FILE)
    expected = parse_version(baseline["torch_version"])
    table = stable_shim_versions()
    for sym in baseline["symbols"]:
        assert table[sym] == expected


def test_version_table_manifest_versions():
    manifest = _load(torch_versions._MANIFEST_FILE)
    table = stable_shim_versions()
    for sym, version in manifest["symbols"].items():
        assert table[sym] == parse_version(version)


def test_baseline_and_manifest_are_disjoint():
    baseline = _load(torch_versions._BASELINE_FILE)
    manifest = _load(torch_versions._MANIFEST_FILE)
    assert not (set(baseline["symbols"]) & set(manifest["symbols"]))


def test_version_table_returns_fresh_copy():
    a = stable_shim_versions()
    a.clear()
    assert stable_shim_versions(), (
        "version_table must not expose a shared mutable table"
    )


def test_data_files_share_schema():
    baseline = _load(torch_versions._BASELINE_FILE)
    manifest = _load(torch_versions._MANIFEST_FILE)
    for data in (baseline, manifest):
        assert isinstance(data["sources"], list) and data["sources"]
        assert isinstance(data["generator"], str)
        assert isinstance(data["generated"], str)
        assert data["symbols"]
    # Baseline additionally names the torch release its symbols predate.
    assert baseline["torch_version"]
