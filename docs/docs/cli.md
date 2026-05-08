---
icon: lucide/terminal
---

# CLI reference

```text
usage: torch-abi-audit [-h] [--version] [--env | --site-packages PATH]
                       [--json] [--all] [-v]
                       [TARGET ...]
```

## Modes

The CLI selects exactly one inspection mode:

| Mode | Flag(s) | What it inspects |
|------|---------|------------------|
| Targets | `TARGET ...` (positional) | One or more import names or filesystem paths. |
| Active env | `--env` | Every package in the running interpreter's site-packages. |
| Specific env | `--site-packages PATH` | Every package under the given site-packages directory. |

A `TARGET` can be:

- An importable name like `torchvision` — resolved via `importlib.util.find_spec`.
- A path to an installed package directory (recursive scan).
- A path to a single `.so` / `.pyd` / `.dylib` file.

## Output

By default the CLI prints a human-readable table.

- `--json` switches to JSON. With multiple targets the output is wrapped
  in an `EnvironmentReport`-shaped envelope so the JSON shape is consistent.
- `--verbose` (`-v`) shows the offending symbol list for unstable / non-compliant
  extensions.
- `--all` makes env-scan output include packages with no torch use (hidden
  by default to keep the table focused on potentially-problematic packages).

## Output examples

All three samples below were captured against `torch 2.11.0`,
`torchaudio 2.11.0`, and `torchcodec 0.11.1` on Linux aarch64.

### Default table — multi-package

`torch-abi-audit torchaudio torch torchcodec`:

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
    [NO-TORCH] [not-abi3              ] lib/libarm_compute.so
    [NO-TORCH] [not-abi3              ] lib/libarm_compute_graph.so
    [NO-TORCH] [not-abi3              ] lib/libc10.so
    [UNSTABLE] [not-abi3              ] lib/libc10_cuda.so  (stable_shim=0, unstable=44)
    [NO-TORCH] [not-abi3              ] lib/libcaffe2_nvrtc.so
    [UNSTABLE] [not-abi3              ] lib/libshm.so  (stable_shim=0, unstable=9)
    [NO-TORCH] [not-abi3              ] lib/libtorch.so
    [UNSTABLE] [not-abi3              ] lib/libtorch_cpu.so  (stable_shim=0, unstable=327)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cuda.so  (stable_shim=0, unstable=2515)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cuda_linalg.so  (stable_shim=0, unstable=143)
    [NO-TORCH] [not-abi3              ] lib/libtorch_global_deps.so
    [UNSTABLE] [not-abi3              ] lib/libtorch_nvshmem.so  (stable_shim=0, unstable=66)
    [UNSTABLE] [uses-private-api      ] lib/libtorch_python.so  (stable_shim=0, unstable=5085)

Package: torchcodec
  Root: <venv>/lib/python3.11/site-packages/torchcodec
  Torch ABI:   UNSTABLE
  CPython ABI: no
  Extensions:  5
  Bundled libs: 10
  -- extensions --
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops4.so
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops5.so
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops6.so
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops7.so
    [NO-TORCH] [uses-private-api      ] libtorchcodec_pybind_ops8.so
  -- bundled libs --
    [UNSTABLE] [not-abi3              ] libtorchcodec_core4.so  (stable_shim=64, unstable=4)
    [UNSTABLE] [not-abi3              ] libtorchcodec_core5.so  (stable_shim=64, unstable=4)
    [UNSTABLE] [not-abi3              ] libtorchcodec_core6.so  (stable_shim=64, unstable=4)
    [UNSTABLE] [not-abi3              ] libtorchcodec_core7.so  (stable_shim=64, unstable=4)
    [UNSTABLE] [not-abi3              ] libtorchcodec_core8.so  (stable_shim=64, unstable=4)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops4.so  (stable_shim=68, unstable=0)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops5.so  (stable_shim=68, unstable=0)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops6.so  (stable_shim=68, unstable=0)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops7.so  (stable_shim=68, unstable=0)
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops8.so  (stable_shim=68, unstable=0)
```

The per-row labels:

| Torch | CPython | Meaning |
|---|---|---|
| `STABLE` / `UNSTABLE` / `NO-TORCH` | — | Per-library torch verdict. |
| — | `abi3-ok` | Filename tagged abi3 *and* every Py\* symbol is in the limited API. |
| — | `abi3-tagged-violations` | Filename tagged abi3 but the file references private CPython symbols. |
| — | `abi3-tagged-no-capi` | Filename tagged abi3, file has no CPython API references at all (e.g. a STABLE_TORCH_LIBRARY plugin). |
| — | `uses-private-api` | Not abi3-tagged, references private CPython symbols. |
| — | `not-abi3` | Not abi3-tagged, no Py\* references. |

### Verbose excerpt — `--verbose` surfaces offending symbols

`torch-abi-audit torch -v` (first 28 lines):

```text
Package: torch
  Root: <venv>/lib/python3.11/site-packages/torch
  Torch ABI:   UNSTABLE
  CPython ABI: no
  Extensions:  1
  Bundled libs: 13
  -- extensions --
    [NO-TORCH] [not-abi3              ] _C.cpython-311-aarch64-linux-gnu.so
  -- bundled libs --
    [NO-TORCH] [not-abi3              ] lib/libarm_compute.so
    [NO-TORCH] [not-abi3              ] lib/libarm_compute_graph.so
    [NO-TORCH] [not-abi3              ] lib/libc10.so
    [UNSTABLE] [not-abi3              ] lib/libc10_cuda.so  (stable_shim=0, unstable=44)
        torch unstable: c10::SetAllocator(c10::DeviceType, c10::Allocator*, unsigned char)
        torch unstable: c10::WarningUtils::get_warnAlways()
        torch unstable: c10::MessageLogger::stream[abi:cxx11]()
        torch unstable: c10::MessageLogger::MessageLogger(c10::SourceLocation, int, bool)
        torch unstable: c10::MessageLogger::~MessageLogger()
        torch unstable: c10::DeviceAllocator::DeviceAllocator()
        torch unstable: c10::DeviceAllocator::~DeviceAllocator()
        torch unstable: c10::SmallVectorBase<unsigned int>::grow_pod(void const*, unsigned long, unsigned long)
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::roundup_power2_divisions(unsigned long)
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::instance()
        torch unstable: c10::reportMemoryUsageToProfiler(void*, long, unsigned long, unsigned long, c10::Device)
        torch unstable: c10::reportOutOfMemoryToProfiler(long, unsigned long, unsigned long, c10::Device)
        torch unstable: c10::ApproximateClockToUnixTimeConverter::makeConverter()
        torch unstable: c10::ApproximateClockToUnixTimeConverter::ApproximateClockToUnixTimeConverter()
        torch unstable: c10::impl::DeviceGuardImplRegistrar::DeviceGuardImplRegistrar(...)
        ... 29 more
```

The first 15 unstable symbols per library are listed inline; anything past
that becomes a `... N more` summary so the table doesn't blow up.

### JSON shape — `--json`

`torch-abi-audit torchaudio --json`:

```json
{
  "name": "torchaudio",
  "root": "<venv>/lib/python3.11/site-packages/torchaudio",
  "extensions": [],
  "bundled_libs": [
    {
      "path": "<venv>/.../torchaudio/lib/_torchaudio.abi3.so",
      "cpython": { "intent": true, "compliant": false, "violations": [] },
      "torch": {
        "uses_torch": true,
        "stable": true,
        "unstable_symbols": [],
        "stable_shim_count": 6
      },
      "error": null
    },
    { "path": "<venv>/.../torchaudio/lib/libtorchaudio.abi3.so", "...": "..." },
    { "path": "<venv>/.../torchaudio/lib/torchaudio_prefixctc.abi3.so", "...": "..." }
  ],
  "error": null
}
```

The verdict roll-ups (`torch_verdict`, `cpython_verdict`) are `@property`
on `PackageReport`, so they're computed on access and don't appear in the
JSON dump. Compute them yourself by looking at the `extensions` and
`bundled_libs` lists, or use the Python API.

## Exit codes

The CLI reports verdicts via stdout / JSON; it returns:

- `0` on inspection success regardless of verdict.
- `2` on operational errors (missing `nm`, unknown import name, unreadable path).

This makes the tool safe to run interactively without `set -e` surprises.
For CI gating, parse the JSON output.
