# torch-abi-audit

Audit Python extension modules for compliance with the
[PyTorch Stable ABI](https://docs.pytorch.org/docs/main/notes/libtorch_stable_abi.html)
(`aoti_torch_*` C shim and `torch::stable::*` / `torch::headeronly::*` C++
wrappers, introduced in PyTorch 2.9). Walks every `.so` shipped in a
package — both Python extension modules and bundled internal libraries —
and reports which stick to the stable surface and which reach into
`at::` / `c10::` / `torch::jit::` internals.

As a side benefit the same symbol-table walk also reports
[CPython Stable ABI](https://docs.python.org/3/c-api/stable.html) (PEP 384)
compliance, since the data is right there.

📖 **Documentation:** <https://quansight.github.io/torch-abi-audit/>

## Install

```bash
pip install torch-abi-audit
```

Linux and macOS only for now (Windows requires `dumpbin` support — not yet implemented).

## CLI usage

```bash
# Inspect an installed PyTorch ecosystem package by import name
torch-abi-audit torchaudio

# Inspect a path to an installed package or a single .so
torch-abi-audit /path/to/site-packages/somepkg

# Inspect every package in the current environment's site-packages
torch-abi-audit --env

# Inspect a specific site-packages directory
torch-abi-audit --site-packages /opt/venv/lib/python3.12/site-packages

# JSON output for tooling
torch-abi-audit --env --json | jq '.packages[] | select(.torch.uses_torch)'
```

## Example output

Run against the three packages tracked by `scripts/check_real_world.py`
(captured against torch 2.11.0 / torchaudio 2.11.0 / torchcodec 0.11.1):

```text
Package: torchaudio
  Root: <venv>/lib/python3.11/site-packages/torchaudio
  Torch ABI:   STABLE
  CPython ABI: n/a
  Extensions:  0
  Bundled libs: 3
  -- bundled libs --
    [STABLE  ] [abi3-tagged-no-capi   ] lib/_torchaudio.abi3.so  (stable_shim=6, unstable=0)
    [STABLE  ] [abi3-tagged-no-capi   ] lib/libtorchaudio.abi3.so  (stable_shim=80, unstable=0)
    [STABLE  ] [abi3-tagged-no-capi   ] lib/torchaudio_prefixctc.abi3.so  (stable_shim=62, unstable=0)

Package: torch
  Root: <venv>/lib/python3.11/site-packages/torch
  Torch ABI:   UNSTABLE
  CPython ABI: no
  Extensions:  1
  Bundled libs: 13
  -- extensions --
    [NO-TORCH] [not-abi3              ] _C.cpython-311-aarch64-linux-gnu.so
  -- bundled libs --
    [UNSTABLE] [not-abi3              ] lib/libc10_cuda.so  (stable_shim=0, unstable=44)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cpu.so  (stable_shim=0, unstable=327)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cuda.so  (stable_shim=0, unstable=2515)
    [UNSTABLE] [uses-private-api      ] lib/libtorch_python.so  (stable_shim=0, unstable=5085)
    ... (9 more, mostly NO-TORCH or UNSTABLE)

Package: torchcodec
  Root: <venv>/lib/python3.11/site-packages/torchcodec
  Torch ABI:   UNSTABLE
  CPython ABI: no
  Extensions:  5
  Bundled libs: 10
  -- extensions --
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops4.so
    ... (4 similar)
  -- bundled libs --
    [UNSTABLE] [not-abi3              ] libtorchcodec_core4.so  (stable_shim=64, unstable=4)
    ... (4 similar)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops4.so  (stable_shim=68, unstable=0)
    ... (4 similar)
```

`torchaudio` is reported as stable because every compiled library it ships
links against `aoti_torch_*` and `torch::stable::*` only. `torch` lands on
`UNSTABLE` because its bundled `libtorch_python.so`, `libtorch_cpu.so`, etc.
naturally reference internal `at::` / `c10::` namespaces (torch *implements*
those internals, after all). `torchcodec` is mid-migration: the
`custom_ops*` libs already use the stable surface, but `core*` libs still
link a handful of `c10::` symbols.

## Python API

```python
from torch_abi_audit import (
    inspect_extension,
    inspect_package,
    inspect_site_packages,
)

report = inspect_package("torchaudio")
print(report.torch_verdict)             # "torch-stable" | "torch-unstable" | "no-torch"

# `extensions` holds Python extension modules; `bundled_libs` holds the
# rest of the compiled .so files (libtorch_python.so, STABLE_TORCH_LIBRARY
# plugins, etc.). Both contribute to the verdict.
for lib in (*report.extensions, *report.bundled_libs):
    print(lib.path, lib.torch.stable, lib.cpython.compliant)
```

## Development

```bash
uv sync                          # install + dev dependencies in .venv
uv run pytest                    # run tests
uv run pyrefly check             # type-check
uv run zensical serve docs/      # local docs server
```

## License

MIT — see [LICENSE](LICENSE).
