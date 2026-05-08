"""Unit tests for the PyTorch ABI classifier — pure logic, no compilation needed."""

from __future__ import annotations

from torch_abi_audit.torch_abi import classify_symbol, classify_symbols


def test_stable_shim_aoti():
    assert classify_symbol("aoti_torch_get_dim") == "stable_shim"
    assert classify_symbol("aoti_torch_create_tensor_from_blob") == "stable_shim"


def test_stable_shim_torch_c():
    assert classify_symbol("torch_call_dispatcher") == "stable_shim"


def test_stable_shim_macho_underscore():
    """Symbol extraction strips macOS underscores, but the regex stays defensive."""
    assert classify_symbol("_aoti_torch_get_dim") == "stable_shim"


def test_unstable_at():
    assert classify_symbol("at::Tensor::numel() const") == "unstable"


def test_unstable_c10():
    assert classify_symbol("c10::Error::Error(c10::SourceLocation, std::string)") == "unstable"


def test_unstable_torch_jit():
    assert classify_symbol("torch::jit::compile_function(std::string const&)") == "unstable"


def test_torch_stable_namespace_is_not_unstable():
    assert classify_symbol("torch::stable::Tensor::dim() const") == "other"


def test_torch_headeronly_namespace_is_not_unstable():
    assert classify_symbol("torch::headeronly::ScalarType_to_string(int)") == "other"


def test_irrelevant_symbol():
    assert classify_symbol("__cxa_atexit") == "other"
    assert classify_symbol("memcpy") == "other"


def test_verdict_pure_stable():
    v = classify_symbols(["aoti_torch_get_dim", "memcpy", "torch::stable::foo()"])
    assert v.uses_torch is True
    assert v.stable is True
    assert v.unstable_symbols == ()
    assert v.stable_shim_count == 1


def test_verdict_unstable_dominates():
    v = classify_symbols([
        "aoti_torch_get_dim",
        "at::Tensor::numel() const",
        "c10::Error::what() const",
    ])
    assert v.uses_torch is True
    assert v.stable is False
    assert len(v.unstable_symbols) == 2
    assert v.stable_shim_count == 1


def test_verdict_no_torch():
    v = classify_symbols(["memcpy", "PyList_New", "fopen"])
    assert v.uses_torch is False
    assert v.stable is False  # not "stable" because there's no torch use at all
    assert v.unstable_symbols == ()
    assert v.stable_shim_count == 0
