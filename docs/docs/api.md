---
icon: lucide/code-2
---

# Python API

The package exposes a small typed API for programmatic use.

## Inspection entry points

```python
from torch_abi_audit import (
    inspect_extension,
    inspect_package,
    inspect_site_packages,
)
```

### `inspect_extension(path) -> ExtensionReport`

Inspect a single extension module file. Returns an `ExtensionReport` even for
unreadable files (the `error` field carries the message).

### `inspect_package(name_or_path) -> PackageReport`

Inspect an installed package. `name_or_path` is either:

- An import name string (e.g. `"torchaudio"`) — resolved via the import system.
- A `Path` (or path-string with a separator) — treated as a file or directory.

The returned `PackageReport` separates Python extension modules
(`.extensions`) from bundled internal libraries (`.bundled_libs`); both
contribute to the torch ABI verdict.

### `inspect_site_packages(directory=None) -> EnvironmentReport`

Walk a site-packages directory, returning one `PackageReport` per package that
contains compiled libraries — extension modules, bundled libraries, or both.
`directory=None` defaults to the active interpreter's `purelib`.

## Result types

All result dataclasses are frozen, slotted, and fully typed.

```python
@dataclass(frozen=True, slots=True)
class CPythonABIVerdict:
    intent: bool         # filename carries an `abi3` tag
    compliant: bool      # all Py*/_Py* symbols are in the stable set
    violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TorchABIVerdict:
    uses_torch: bool
    stable: bool
    unstable_symbols: tuple[str, ...]
    stable_shim_count: int
    min_torch_version: str | None
    version_defining_symbols: tuple[str, ...]
    unknown_shim_symbols: tuple[str, ...]        # shims newer than the vendored data


@dataclass(frozen=True, slots=True)
class ExtensionReport:
    path: Path
    cpython: CPythonABIVerdict
    torch: TorchABIVerdict
    error: str | None


@dataclass(frozen=True, slots=True)
class PackageReport:
    name: str
    root: Path
    extensions: tuple[ExtensionReport, ...]      # PyInit_*-bearing .so files
    bundled_libs: tuple[ExtensionReport, ...]    # other compiled .so files in the package
    error: str | None
    # @property torch_verdict     -> "torch-stable" | "torch-unstable" | "no-torch" | "error"
    # @property min_torch_version -> "2.10.0"-style floor across all libs, or None
    # @property min_torch_display -> same, ">="-prefixed when unknown newer shims are present
    # @property cpython_verdict   -> "abi3-compliant" | "not-abi3" | "mixed" | "no-extensions"


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    site_packages: Path
    packages: tuple[PackageReport, ...]
```

## Formatters

```python
from torch_abi_audit.report import (
    format_json,
    format_package_table,
    format_environment_table,
)
```

`format_json` accepts any of the three top-level report types and emits
indented JSON. The table formatters are package- and environment-specific.

## Minimum torch version

The stable ABI grows over time: new `aoti_torch_*` / `torch_*` C-shim entry
points appear in later releases. `torch_abi_audit.torch_versions` maps each
stable shim symbol to the torch release that introduced it, using a vendored
copy of PyTorch's
[`shim_function_versions.txt`](https://github.com/pytorch/pytorch/blob/main/torch/csrc/stable/c/shim_function_versions.txt).
That manifest lists only 2.10.0+ symbols, so a second vendored file,
`baseline_shim_symbols.json`, records the fixed set that existed at 2.9.0. A
shim symbol in neither file is *newer than our data* and is surfaced rather than
silently treated as 2.9.0 (which would misdate wheels built against a future
torch).

```python
from torch_abi_audit import BASELINE_VERSION, minimum_version, symbol_version

symbol_version("torch_has_storage")   # (2, 14, 0)
symbol_version("aoti_torch_get_dim")  # None (in the 2.9.0 baseline, not the manifest)

# minimum_version returns (version_tuple, defining_symbols, unknown_symbols):
# version is the highest floor across the *known* symbols (BASELINE_VERSION,
# 2.9.0, when the stable ABI shipped, if none are newer); unknown lists shims in
# neither data file.
minimum_version(["aoti_torch_aten_full", "torch_has_storage"])
# -> ((2, 14, 0), ("torch_has_storage",), ())
minimum_version(["aoti_torch_get_dim", "aoti_torch_from_the_future"])
# -> ((2, 9, 0), (), ("aoti_torch_from_the_future",))
```

`classify_symbols` already runs this for you: the resulting `TorchABIVerdict`
carries `min_torch_version` (a `"2.10.0"`-style string), `version_defining_symbols`,
and `unknown_shim_symbols`. Refresh the vendored data with
`python scripts/update_shim_versions.py` and `python scripts/generate_baseline_shims.py`.

## Example

```python
from torch_abi_audit import inspect_site_packages

env = inspect_site_packages()
unstable = [p.name for p in env.packages if p.torch_verdict == "torch-unstable"]
print("Packages using unstable libtorch ABI:", unstable)

# Which minimum torch version does each stable-ABI package need?
for p in env.packages:
    if p.min_torch_version:
        print(f"{p.name}: needs torch >= {p.min_torch_version}")
```
