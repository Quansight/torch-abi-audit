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
    # @property torch_verdict   -> "torch-stable" | "torch-unstable" | "no-torch" | "error"
    # @property cpython_verdict -> "abi3-compliant" | "not-abi3" | "mixed" | "no-extensions"


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

## Example

```python
from torch_abi_audit import inspect_site_packages

env = inspect_site_packages()
unstable = [p.name for p in env.packages if p.torch_verdict == "torch-unstable"]
print("Packages using unstable libtorch ABI:", unstable)
```
