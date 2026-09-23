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

Package headers carry a `Min torch:` line, mirrored by the env-scan
`MIN-TORCH` column: the lowest torch release that supplies every stable shim symbol the
package references (see [Minimum torch version](#minimum-torch-version)). Each
stable-ABI library row also gains a `min-torch=<version>` suffix, and
`--verbose` lists the shim symbols that pin the floor.

## Output examples

All samples below were captured against `torch 2.14.0`, `torchaudio 2.11.0`,
and `torchcodec 0.16.0` on Linux x86_64.

### Default table -- multi-package

`torch-abi-audit torchaudio torch torchcodec`:

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
    [NO-TORCH] [not-abi3              ] lib/libc10.so
    [UNSTABLE] [not-abi3              ] lib/libc10_cuda.so  (stable_shim=0, unstable=48)
    [NO-TORCH] [not-abi3              ] lib/libcaffe2_nvrtc.so
    [UNSTABLE] [not-abi3              ] lib/libshm.so  (stable_shim=0, unstable=9)
    [NO-TORCH] [not-abi3              ] lib/libtorch.so
    [UNSTABLE] [not-abi3              ] lib/libtorch_cpu.so  (stable_shim=0, unstable=343)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cuda.so  (stable_shim=0, unstable=2569)
    [UNSTABLE] [not-abi3              ] lib/libtorch_cuda_linalg.so  (stable_shim=0, unstable=156)
    [NO-TORCH] [not-abi3              ] lib/libtorch_global_deps.so
    [UNSTABLE] [not-abi3              ] lib/libtorch_nvshmem.so  (stable_shim=0, unstable=74)
    [UNSTABLE] [uses-private-api      ] lib/libtorch_python.so  (stable_shim=0, unstable=5111)

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
    [STABLE  ] [not-abi3              ] libtorchcodec_core5.so  (stable_shim=67, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_core6.so  (stable_shim=67, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_core7.so  (stable_shim=67, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_core8.so  (stable_shim=67, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_core9.so  (stable_shim=67, unstable=0)  min-torch=2.11.0
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops4.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops5.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops6.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops7.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops8.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    [STABLE  ] [uses-private-api      ] libtorchcodec_custom_ops9.so  (stable_shim=65, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_heic.so  (stable_shim=60, unstable=0)  min-torch=2.11.0
    [STABLE  ] [not-abi3              ] libtorchcodec_image.so  (stable_shim=72, unstable=0)  min-torch=2.11.0
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

### Verbose excerpt -- `--verbose` surfaces offending symbols

`torch-abi-audit torch -v` (first 28 lines):

```text
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
    [NO-TORCH] [not-abi3              ] lib/libc10.so
    [UNSTABLE] [not-abi3              ] lib/libc10_cuda.so  (stable_shim=0, unstable=48)
        torch unstable: c10::ValueError::ValueError(c10::SourceLocation, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char>>)
        torch unstable: c10::SetAllocator(c10::DeviceType, c10::Allocator*, unsigned char)
        torch unstable: c10::WarningUtils::get_warnAlways()
        torch unstable: c10::MessageLogger::stream[abi:cxx11]()
        torch unstable: c10::MessageLogger::MessageLogger(c10::SourceLocation, int, bool)
        torch unstable: c10::MessageLogger::~MessageLogger()
        torch unstable: c10::DeviceAllocator::DeviceAllocator()
        torch unstable: c10::DeviceAllocator::~DeviceAllocator()
        torch unstable: c10::SmallVectorBase<unsigned int>::grow_pod(void const*, unsigned long, unsigned long)
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::getMutableKeys[abi:cxx11]()
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::getConfigParserHook[abi:cxx11]()
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::roundup_power2_divisions(unsigned long)
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::getKeys[abi:cxx11]()
        torch unstable: c10::CachingAllocator::AcceleratorAllocatorConfig::instance()
        torch unstable: c10::OutOfMemoryError::OutOfMemoryError(c10::SourceLocation, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char>>)
        ... 33 more
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
        "stable_shim_count": 6,
        "min_torch_version": "2.10.0",
        "version_defining_symbols": ["torch_library_impl"],
        "unknown_shim_symbols": []
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

## Minimum torch version

Every stable shim entry point was introduced in some torch release. The tool
maps each one to its introducing version (via a vendored copy of PyTorch's
`shim_function_versions.txt`) and reports the highest such version a library
needs, its **minimum torch version floor**. Shim symbols from the `2.9.0`
baseline (when the stable ABI shipped) count as `2.9.0`. A shim symbol newer
than the vendored data is reported separately (`unknown_shim_symbols`, shown
under `--verbose`) and turns the floor into a lower bound, displayed as
`min-torch=>=<version>`; regenerate the data files to resolve it.

With `--verbose`, each stable library's floor is followed by the shim symbols
that pin it (`torchaudio -v`, captured against torchaudio 2.11.0):

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
        requires torch 2.10.0: torch_library_impl
    [STABLE  ] [abi3-tagged-no-capi   ] lib/libtorchaudio.abi3.so  (stable_shim=80, unstable=0)  min-torch=2.11.0
        requires torch 2.11.0: torch_dtype_float4_e2m1fn_x2, torch_dtype_float8_e8m0fnu
    [STABLE  ] [abi3-tagged-no-capi   ] lib/torchaudio_prefixctc.abi3.so  (stable_shim=62, unstable=0)  min-torch=2.10.0
        requires torch 2.10.0: torch_call_dispatcher, torch_delete_list, torch_get_mutable_data_ptr, torch_library_impl, torch_list_push_back, +1 more
```

In the env-scan table the same floor appears as the `MIN-TORCH` column
(`-` when a package uses no stable shims):

```text
  PACKAGE           TORCH     MIN-TORCH  CPYTHON   EXTS  BUNDLED
  ----------------  --------  ---------  --------  ----  -------
  torch             UNSTABLE  -          no           1       11
  torchaudio        STABLE    2.11.0     n/a          0        3
  torchcodec        STABLE    2.11.0     no           1       14
```

Refresh the vendored version table from pytorch/pytorch with:

```bash
python scripts/update_shim_versions.py          # rewrite the vendored copy
python scripts/update_shim_versions.py --check  # CI: fail if it's stale
```

## Exit codes

The CLI reports verdicts via stdout / JSON; it returns:

- `0` on inspection success regardless of verdict.
- `2` on operational errors (missing `nm`, unknown import name, unreadable path).

This makes the tool safe to run interactively without `set -e` surprises.
For CI gating, parse the JSON output.
