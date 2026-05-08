---
icon: lucide/scan-search
---

# torch-abi-audit

A small tool to audit compiled Python extension modules for compliance with
the **PyTorch Stable ABI** ([PyTorch 2.9+](https://pytorch.org/blog/pytorch-2-9/))
— the `aoti_torch_*` C shim plus `torch::stable::*` / `torch::headeronly::*`
C++ wrappers that let custom PyTorch extensions survive PyTorch upgrades.

As a side benefit, the same symbol-table walk also reports compliance with
the **CPython Stable ABI** ([PEP 384](https://peps.python.org/pep-0384/)) —
the "limited API" that lets a single wheel work across CPython versions.

## Status of the PyTorch ecosystem

A snapshot of where things stand as of May 2026. These are illustrative
examples — not an exhaustive list — and more projects are being ported
all the time, so this may be out of date by the time you read it.

Migration completed:

- [torchao](https://github.com/pytorch/ao)
- [torchaudio](https://github.com/pytorch/audio)
- [FlashAttention-3](https://github.com/Dao-AILab/flash-attention)
- [xformers](https://github.com/facebookresearch/xformers)

In progress:

- [torchcodec](https://github.com/pytorch/torchcodec)
- [torchvision](https://github.com/pytorch/vision)
- [vLLM](https://github.com/vllm-project/vllm)
- [kvcached](https://github.com/ovg-project/kvcached)

Gaps in the stable surface still get filled in as downstream projects hit
them, so the list of "completed" packages will keep growing.

## Resources

- **PyTorch docs** — [LibTorch Stable ABI](https://docs.pytorch.org/docs/main/notes/libtorch_stable_abi.html)
  (canonical reference, three-layer breakdown).
- **PyTorch Conference Europe 2026** — *How to write C++ extensions in 2026*,
  Jane Xu & Mikayla Gawarecki (Meta):
  [schedule entry](https://pytorchconferenceeu2026.sched.com/event/2Hip2/how-to-write-c++-extensions-in-2026-jane-xu-meta-mikayla-gawarecki-meta)
  · [slides (PDF)](https://hosted-files.sched.co/pytorchconferenceeu2026/49/PTC%20EU%202026_%20How%20to%20Write%20C%2B%2B%20Extensions%20in%202026.pdf)
- **Plans** — [LibTorch ABI Stable Plans 2026](https://dev-discuss.pytorch.org/t/libtorch-abi-stable-plans-2026/3380) on dev-discuss.

## Why

CPython's stable-ABI ecosystem has [`abi3audit`](https://github.com/pypa/abi3audit)
for compliance checking. The PyTorch side is brand new and there's no
equivalent yet — this fills that gap, and handles both checks in one pass.

## Install

```bash
pip install torch-abi-audit
```

Linux and macOS only. Windows support requires a `dumpbin`-based backend that
isn't implemented yet.

## Quick tour

```bash
# Inspect a single installed package by import name
torch-abi-audit torchaudio

# Or by path to its install directory or a single .so
torch-abi-audit /path/to/site-packages/torchaudio

# Whole-environment scan (active interpreter)
torch-abi-audit --env

# Specific site-packages directory + JSON
torch-abi-audit --site-packages /opt/venv/lib/python3.12/site-packages --json
```

The verdict types come straight from the symbol table: a torch-using library
is reported as `STABLE` only if it links exclusively against the documented
stable surface, and as `UNSTABLE` if any `c10::*`, `at::*`, or non-stable
`torch::*` symbol is referenced.

## How it works

1. Walk the target directory and collect every `.so` / `.pyd` / `.dylib`.
   Bucket each by whether it defines a `PyInit_*` symbol — Python extension
   modules go under `extensions`, internal bundled libraries (e.g.
   `torch/lib/libtorch_python.so`, or torchaudio's stable plugins loaded
   via `STABLE_TORCH_LIBRARY`) go under `bundled_libs`. Both buckets count
   toward the PyTorch verdict; only `extensions` count toward the CPython
   ABI verdict.
2. Run `nm -uD` (Linux) or `nm -u` (macOS) to extract undefined symbols.
3. Demangle C++ names via [pycxxfilt](https://pypi.org/project/pycxxfilt/).
4. Classify each symbol against two rule sets — the CPython stable-ABI
   symbol set from [abi3info](https://pypi.org/project/abi3info/) and the
   PyTorch stable namespace regexes.
5. Roll up per-library verdicts to a per-package and per-environment view.
