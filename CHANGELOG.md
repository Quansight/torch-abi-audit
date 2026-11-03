# Changelog

## Unreleased

- Support Windows: PE/COFF import and export tables are parsed directly, so
  `.pyd` extension modules and bundled `.dll` libraries (e.g.
  `torch/lib/torch_cpu.dll`) are audited like their ELF and Mach-O
  counterparts. Directory scans collect `.pyd`/`.dll` on Windows and keep
  their existing `.so`/`.pyd`/`.dylib` set on Linux and macOS. `dumpbin` is
  used when it is on `PATH`, with the built-in parser as the fallback, so no
  external tool is required.
- Check the Python DLL a Windows extension links: a Stable ABI build must use
  `python3.dll`, and one linked against a version-specific `python3XX.dll` is
  reported as non-compliant even when all of its symbols are stable.
- Inspect a Windows binary by path on any host. The built-in PE parser is
  self-contained, so a `.pyd`/`.dll` named explicitly is read from Linux or
  macOS too; ELF and Mach-O inspection still relies on the host's `nm`, so this
  is not a general cross-platform scan.
- Keep the symbols recovered from a damaged table and report the partial read
  as an inspection error (exit `2`), instead of discarding the whole directory
  and quietly reporting the library as torch-free. Symbol names longer than
  4096 characters are no longer treated as corruption.
- Demangle MSVC C++ names (`?...`) in addition to Itanium ones.
- Add Windows to the test matrix. The C/C++ fixtures are built with MSVC, so a
  Windows run has to start from a Visual Studio developer prompt (or a shell
  with the MSVC environment initialised); a missing `cl` fails those tests
  instead of skipping them. Linux and macOS keep their existing compiler
  discovery and skip behaviour.

## 0.3.0

- Add `--check {torch,abi3,both}` for CI gating, with exit code 1 for ABI
  policy violations. The `abi3` policy checks CPython ABI compliance of
  extension modules in torch-using packages.
- Return exit code 2 for inspection errors recorded on packages or individual
  libraries in both target and environment scans, with or without `--check`.
  Operational errors take precedence over policy violations.
- Document the CI gate policies and exit codes, with usage examples.
- Require pycxxfilt 1.2.0 or newer and use its native GNU symbol-version
  support, replacing the local workaround while preserving `@` and `@@`
  suffixes in demangled names.

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
