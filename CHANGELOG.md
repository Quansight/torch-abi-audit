# Changelog

## 0.2.0

- Report the minimum PyTorch version required by a library's stable C-shim
  symbols, with a package-wide roll-up across extension modules and bundled
  libraries. Expose version information in the Python API, text output, and
  per-library JSON output.
- Show the symbols that determine the minimum PyTorch version in verbose
  output, including verbose environment scans.
- Vendor PyTorch's shim introduction-version data and the complete PyTorch
  2.9.0 baseline symbol set, including deprecated shims. Add regeneration
  scripts and a `stable_shim_versions()` lookup API.
- Flag shim symbols absent from the vendored data and display the known
  minimum version as a lower bound rather than silently treating unknown
  symbols as part of the 2.9.0 baseline.
- Recognize Python 3.15's `PyModExport_` module entry points (PEP 793), as well
  as the `PyModExportU_` and `PyInitU_` variants for non-ASCII module names,
  so these extensions are correctly distinguished from bundled libraries.
- Add Python 3.15 CI coverage on Linux and macOS, including a compiled
  `PyModExport_` regression fixture.
- Expand the documentation on PyTorch ecosystem migration to the stable ABI
  and document minimum-version reporting with updated output examples.
- Update locked development dependencies.

## 0.0.1

- First release.
- Audit Python extension modules and bundled shared libraries for PyTorch
  Stable ABI usage and CPython Stable ABI compliance on Linux and macOS.
- Provide a CLI and Python API for inspecting individual libraries, installed
  packages, and whole environments, with text and JSON reports.
