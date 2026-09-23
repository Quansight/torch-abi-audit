# torch-abi-audit

Audit Python extension modules for compliance with the
[PyTorch Stable ABI](https://docs.pytorch.org/docs/main/notes/libtorch_stable_abi.html)
(`aoti_torch_*` C shim and `torch::stable::*` / `torch::headeronly::*` C++
wrappers, introduced in PyTorch 2.9). Walks every `.so` shipped in a
package — both Python extension modules and bundled internal libraries —
and reports which stick to the stable surface and which reach into
`at::` / `c10::` / `torch::jit::` internals.

The audit also reports the **minimum torch version** each library needs: every
`aoti_torch_*` / `torch_*` C-shim entry point was introduced in some release,
and the tool maps each one to its version (using a vendored copy of PyTorch's
[`shim_function_versions.txt`](https://github.com/pytorch/pytorch/blob/main/torch/csrc/stable/c/shim_function_versions.txt))
to compute the lowest torch release a binary can run against.

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
(captured against torch 2.14.0 / torchaudio 2.11.0 / torchcodec 0.16.0 on
Linux x86_64):

```text
Package: torchaudio
  Root: <venv>/lib/python3.11/site-packages/torchaudio
  Torch ABI:   STABLE
  Min torch:   2.11.0
  CPython ABI: n/a
  Extensions:  0
  Bundled libs: 3
  -- bundled libs --
    [STABLE  ] [abi3-tagged-no-capi   ] lib/_torchaudio.abi3.so  (stable_shim=6, unstable=0)  min-torch=2.10.0
    [STABLE  ] [abi3-tagged-no-capi   ] lib/libtorchaudio.abi3.so  (stable_shim=80, unstable=0)  min-torch=2.11.0
    [STABLE  ] [abi3-tagged-no-capi   ] lib/torchaudio_prefixctc.abi3.so  (stable_shim=62, unstable=0)  min-torch=2.10.0

Package: torch
  Root: <venv>/lib/python3.11/site-packages/torch
  Torch ABI:   UNSTABLE
  Min torch:   n/a
  CPython ABI: no
  Extensions:  1
  Bundled libs: 11
  -- extensions --
    [NO-TORCH] [not-abi3              ] _C.cpython-311-x86_64-linux-gnu.so
  -- bundled libs --
    [UNSTABLE] [not-abi3              ] lib/libc10_cuda.so  (stable_shim=0, unstable=48)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cpu.so  (stable_shim=0, unstable=343)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cuda.so  (stable_shim=0, unstable=2569)
    [UNSTABLE] [uses-private-api      ] lib/libtorch_python.so  (stable_shim=0, unstable=5111)
    ... (7 more, mostly NO-TORCH or UNSTABLE)

Package: torchcodec
  Root: <venv>/lib/python3.11/site-packages/torchcodec
  Torch ABI:   STABLE
  Min torch:   2.11.0
  CPython ABI: no
  Extensions:  1
  Bundled libs: 14
  -- extensions --
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops.so
  -- bundled libs --
    [STABLE  ] [not-abi3              ] libtorchcodec_core4.so  (stable_shim=67, unstable=0)  min-torch=2.11.0
    ... (5 more core* libs, identical)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops4.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    ... (5 more custom_ops* libs, identical)
    [STABLE  ] [not-abi3              ] libtorchcodec_heic.so  (stable_shim=60, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_image.so  (stable_shim=72, unstable=0)  min-torch=2.11.0
```

`torchaudio` and `torchcodec` are reported as stable because every compiled
library they ship links against `aoti_torch_*` / `torch_*` and
`torch::stable::*` only (torchcodec completed its migration by 0.16.0). `torch`
lands on `UNSTABLE` because its bundled `libtorch_python.so`, `libtorch_cpu.so`,
etc. naturally reference internal `at::` / `c10::` namespaces (torch
*implements* those internals, after all).

The `Min torch` line (and per-library `min-torch=` suffix) reports the lowest
torch release that supplies every stable shim symbol referenced: a floor of
`2.9.0` (the baseline where the stable ABI shipped) up to whatever the newest
shim used requires. Here both torchaudio and torchcodec need `2.11.0`, driven
by shims like `torch_from_blob` and the `torch_dtype_float8_e8m0fnu` /
`torch_dtype_float4_e2m1fn_x2` dtype handles. `torch` shows `n/a` because its
bundled libraries reference no stable shim symbols at all (they *are*
libtorch). `--verbose` lists the symbols that pin the floor.

## Python API

```python
from torch_abi_audit import (
    inspect_extension,
    inspect_package,
    inspect_site_packages,
)

report = inspect_package("torchaudio")
print(report.torch_verdict)             # "torch-stable" | "torch-unstable" | "no-torch"
print(report.min_torch_version)         # e.g. "2.10.0", or None if no stable shims used

# `extensions` holds Python extension modules; `bundled_libs` holds the
# rest of the compiled .so files (libtorch_python.so, STABLE_TORCH_LIBRARY
# plugins, etc.). Both contribute to the verdict.
for lib in (*report.extensions, *report.bundled_libs):
    print(lib.path, lib.torch.stable, lib.torch.min_torch_version, lib.cpython.compliant)
```

## Development

```bash
uv sync                          # install + dev dependencies in .venv
uv run pytest                    # run tests
uv run pyrefly check             # type-check
uv run zensical serve docs/      # local docs server
```

The minimum-version table is vendored from PyTorch; refresh it with
`python scripts/update_shim_versions.py`. See
`src/torch_abi_audit/data/README.md`.

## License

MIT — see [LICENSE](LICENSE).
