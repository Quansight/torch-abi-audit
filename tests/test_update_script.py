"""Tests for scripts/update_shim_versions.py (the JSON regeneration logic)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_shim_versions.py"


@pytest.fixture(scope="module")
def upd():
    spec = importlib.util.spec_from_file_location("update_shim_versions", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_manifest_skips_comments_and_blanks(upd):
    table = upd._parse_manifest(
        "# header\n\nbrand_new_shim: TORCH_VERSION_2_99_0\nbad line\n"
    )
    assert table == {"brand_new_shim": (2, 99, 0)}


def test_render_payload_is_sorted_string_json(upd):
    payload = upd._render_payload(
        {"b_sym": (2, 10, 0), "a_sym": (2, 14, 0)}, "http://x", "2099-01-01"
    )
    data = json.loads(payload)
    assert data == {
        "sources": ["http://x"],
        "generator": "scripts/update_shim_versions.py",
        "generated": "2099-01-01",
        "symbols": {"a_sym": "2.14.0", "b_sym": "2.10.0"},
    }
    # Keys are emitted in sorted order for a stable diff.
    assert list(data["symbols"]) == ["a_sym", "b_sym"]


def _fake_urlopen(text: str):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return text.encode("utf-8")

    return lambda url: _Resp()


def test_refresh_writes_json_and_is_idempotent(upd, tmp_path, monkeypatch):
    fake = tmp_path / "data" / "shim_function_versions.json"
    upstream = (
        "# header\n"
        "brand_new_shim: TORCH_VERSION_2_99_0\n"
        "another_shim: TORCH_VERSION_2_10_0\n"
    )
    monkeypatch.setattr(upd, "_data_file_path", lambda: fake)
    monkeypatch.setattr(upd.urllib.request, "urlopen", _fake_urlopen(upstream))

    dest, changed = upd.refresh(ref="somebranch", generated="2099-01-01")
    assert dest == fake
    assert changed is True
    written = json.loads(fake.read_text(encoding="utf-8"))
    assert written["symbols"] == {"another_shim": "2.10.0", "brand_new_shim": "2.99.0"}
    assert any("somebranch" in s for s in written["sources"])
    assert written["generated"] == "2099-01-01"

    # Identical upstream -> no rewrite (symbols unchanged), so the date is kept.
    _, changed_again = upd.refresh(ref="somebranch", generated="2099-12-31")
    assert changed_again is False
    assert json.loads(fake.read_text(encoding="utf-8"))["generated"] == "2099-01-01"

    assert upd.is_stale("somebranch") is False


def test_is_stale_detects_new_symbol(upd, tmp_path, monkeypatch):
    fake = tmp_path / "data" / "shim_function_versions.json"
    monkeypatch.setattr(upd, "_data_file_path", lambda: fake)
    monkeypatch.setattr(
        upd.urllib.request, "urlopen", _fake_urlopen("s: TORCH_VERSION_2_10_0\n")
    )
    assert upd.is_stale("main") is True  # vendored file absent
