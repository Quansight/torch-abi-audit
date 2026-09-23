"""Tests for torch_abi_audit.torch_versions: version data and min-version logic."""

from __future__ import annotations

import pytest

from torch_abi_audit import torch_versions
from torch_abi_audit.torch_abi import classify_symbols
from torch_abi_audit.torch_versions import (
    BASELINE_VERSION,
    format_version,
    minimum_version,
    parse_version,
    stable_shim_versions,
    symbol_version,
)

_load = torch_versions._load


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2.10.0", (2, 10, 0)), ("2.9.0", (2, 9, 0)), (" 3.0.1 ", (3, 0, 1))],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    "bad", ["2.10", "2.x.0", "", "2.10.0.1", "TORCH_VERSION_2_10_0"]
)
def test_parse_version_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


def test_format_version_roundtrips():
    assert format_version(parse_version("2.14.0")) == "2.14.0"
    assert format_version((2, 10, 0)) == "2.10.0"


# --- stable_shim_versions (merged baseline + manifest table) --------------


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
    baseline_symbols = set(baseline["symbols"])
    assert baseline_symbols
    assert baseline_symbols.isdisjoint(manifest["symbols"])
    # All baseline entries are shim linker symbols.
    assert all(s.startswith(("aoti_torch_", "torch_")) for s in baseline_symbols)


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


# --- symbol_version / minimum_version ------------------------------------


def test_symbol_version_known():
    assert symbol_version("aoti_torch_aten_full") == (2, 10, 0)
    assert symbol_version("torch_has_storage") == (2, 14, 0)


def test_symbol_version_unlisted_returns_none():
    # A baseline shim symbol is not in the 2.10.0+ manifest.
    assert symbol_version("aoti_torch_get_dim") is None


def test_minimum_version_empty():
    assert minimum_version([]) == (None, (), ())


def test_minimum_version_baseline_symbol():
    """A symbol in the 2.9.0 baseline set floors at BASELINE_VERSION, not unknown."""
    version, defining, unknown = minimum_version(["aoti_torch_get_dim"])
    assert version == BASELINE_VERSION
    assert defining == ()  # baseline is implied, not pinned by a named symbol
    assert unknown == ()


def test_minimum_version_takes_the_max():
    version, defining, unknown = minimum_version(
        ["aoti_torch_get_dim", "aoti_torch_aten_full", "torch_has_storage"]
    )
    assert version == (2, 14, 0)
    assert defining == ("torch_has_storage",)
    assert unknown == ()


def test_minimum_version_reports_all_defining_symbols_at_the_floor():
    version, defining, unknown = minimum_version(
        ["torch_has_storage", "torch_tensor_from_pyobject", "aoti_torch_aten_full"]
    )
    assert version == (2, 14, 0)
    # Both 2.14.0 symbols are named as the reason for the floor, sorted.
    assert defining == ("torch_has_storage", "torch_tensor_from_pyobject")
    assert unknown == ()


def test_minimum_version_unknown_symbol_is_not_floored_at_baseline():
    """A shim symbol in neither data file is surfaced, not silently 2.9.0.

    A wheel built against a *future* torch references shims we have never heard
    of; they must not read as 2.9.0.
    """
    version, defining, unknown = minimum_version(
        ["aoti_torch_get_dim", "aoti_torch_from_the_future"]
    )
    # Known baseline symbol still pins the (lower-bound) floor...
    assert version == BASELINE_VERSION
    assert defining == ()
    # ...but the unrecognised symbol is reported separately.
    assert unknown == ("aoti_torch_from_the_future",)


def test_minimum_version_strips_macho_underscore():
    """A leading underscore (Mach-O prefix) is normalised before lookup."""
    version, _, unknown = minimum_version(["_aoti_torch_aten_full"])
    assert version == (2, 10, 0)
    assert unknown == ()


# --- integration with the classifier -------------------------------------


def test_classify_symbols_populates_min_version():
    v = classify_symbols(["aoti_torch_get_dim", "aoti_torch_aten_full", "memcpy"])
    assert v.uses_torch is True
    assert v.stable is True
    assert v.min_torch_version == "2.10.0"
    assert v.version_defining_symbols == ("aoti_torch_aten_full",)


def test_classify_symbols_no_torch_has_no_min_version():
    v = classify_symbols(["memcpy", "PyList_New"])
    assert v.uses_torch is False
    assert v.min_torch_version is None
    assert v.version_defining_symbols == ()


def test_classify_symbols_baseline_when_only_old_shims():
    v = classify_symbols(["aoti_torch_get_dim", "torch_call_dispatcher"])
    # torch_call_dispatcher is listed at 2.10.0, so the floor is 2.10.0.
    assert v.min_torch_version == "2.10.0"


def test_classify_symbols_unstable_still_reports_shim_floor():
    """An unstable binary that also touches newer shims still reports its floor."""
    v = classify_symbols(["at::Tensor::numel() const", "torch_has_storage"])
    assert v.stable is False
    assert v.min_torch_version == "2.14.0"


def test_classify_symbols_accepts_macho_underscored_shim():
    """A Mach-O-prefixed shim name (direct API caller) resolves like the bare name.

    Extraction strips the leading underscore, but the classifier explicitly
    accepts it via `_?`, so the version lookup must normalise it too. See PR #4.
    """
    v = classify_symbols(["_torch_has_storage"])
    assert v.stable is True
    assert v.min_torch_version == "2.14.0"


def test_classify_symbols_surfaces_unknown_shim_symbols():
    v = classify_symbols(["aoti_torch_aten_full", "aoti_torch_from_the_future"])
    assert v.min_torch_version == "2.10.0"  # lower bound from the known symbol
    assert v.unknown_shim_symbols == ("aoti_torch_from_the_future",)


# --- vendored data integrity ---------------------------------------------


def test_vendored_json_is_pre_parsed():
    data = _load(torch_versions._MANIFEST_FILE)
    # Symbols map to "major.minor.patch" strings; a date stamp is present.
    assert data["symbols"]["torch_has_storage"] == "2.14.0"
    assert data["generated"]
