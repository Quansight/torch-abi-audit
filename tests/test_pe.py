"""PE/COFF symbol extraction tests.

The images are synthesised in-process (:mod:`pe_builder`), so these run on every
OS and need no compiler. Real-world behaviour is covered by the module's own
docs and by auditing actual Windows wheels in CI.
"""

from __future__ import annotations

import mmap
import os
import struct
import sys
from pathlib import Path

import pytest

from pe_builder import PEBuilder, write_pe
from torch_abi_audit import inspect_package, inspect_site_packages, pe, symbols, torch_abi
from torch_abi_audit.cli import main
from torch_abi_audit.pe import PEFormatError, PEImageData, read_pe
from torch_abi_audit.symbols import (
    extract_undefined_symbols,
    find_compiled_libraries,
    is_extension_module,
    read_symbols,
)

# MSVC-mangled references, as found in the import tables of real Windows wheels.
AT_TENSOR_NUMEL = "?numel@Tensor@at@@QEBA_JXZ"
STABLE_TENSOR_DIM = "?dim@Tensor@stable@torch@@QEBA_JXZ"
AOTI_GET_DIM = "aoti_torch_get_dim"
CPYTHON_UNSTABLE = "_PyDict_NewPresized"
CPYTHON_STABLE = "PyModule_Create2"


def test_reads_imports_and_exports(tmp_path: Path) -> None:
    image = write_pe(
        tmp_path / "demo.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_export("PyModExport_demo")
        .add_import("python314.dll", CPYTHON_STABLE)
        .add_import("torch_cpu.dll", AOTI_GET_DIM),
    )

    data = read_pe(image)

    assert data.exports == ("PyInit_demo", "PyModExport_demo")
    # Group order follows the import descriptors; entries keep table order.
    assert data.imports == (CPYTHON_STABLE, AOTI_GET_DIM)
    assert data.libraries == ("python314.dll", "torch_cpu.dll")
    assert data.errors == ()


def test_ordinal_only_imports_are_skipped(tmp_path: Path) -> None:
    image = write_pe(
        tmp_path / "demo.dll",
        PEBuilder()
        .add_import("python314.dll", CPYTHON_STABLE)
        .add_import("python314.dll", None),
    )

    data = read_pe(image)

    assert data.imports == (CPYTHON_STABLE,)
    assert data.exports == ()


@pytest.mark.parametrize(
    ("pe32_plus", "rva_based"),
    [(True, True), (False, True), (False, False)],
)
def test_delay_imports(tmp_path: Path, pe32_plus: bool, rva_based: bool) -> None:
    """Both delay-load descriptor flavours: RVAs since VS6, plain VAs before.

    The VA form only exists for 32-bit images — descriptor fields are DWORDs, so
    a 64-bit image base cannot be stored in them.
    """
    image = write_pe(
        tmp_path / "demo.pyd",
        PEBuilder(pe32_plus=pe32_plus).add_delay_import(
            "torch_cpu.dll", AOTI_GET_DIM, rva_based=rva_based
        ),
    )

    data = read_pe(image)

    assert data.imports == (AOTI_GET_DIM,)
    assert data.libraries == ("torch_cpu.dll",)


@pytest.mark.parametrize("pe32_plus", [True, False])
def test_both_optional_header_formats(tmp_path: Path, pe32_plus: bool) -> None:
    image = write_pe(
        tmp_path / ("demo64.pyd" if pe32_plus else "demo32.pyd"),
        PEBuilder(pe32_plus=pe32_plus)
        .add_export("PyInit_demo")
        .add_import("torch_cpu.dll", AOTI_GET_DIM),
    )

    data = read_pe(image)

    assert data.exports == ("PyInit_demo",)
    assert data.imports == (AOTI_GET_DIM,)


def test_image_without_tables(tmp_path: Path) -> None:
    image = write_pe(tmp_path / "empty.dll", PEBuilder())

    data = read_pe(image)

    assert data == PEImageData()


def test_rejects_non_pe(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.dll"
    bogus.write_bytes(b"not a pe image at all")

    with pytest.raises(PEFormatError):
        read_pe(bogus)


def test_rejects_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pyd"
    empty.touch()

    with pytest.raises(PEFormatError):
        read_pe(empty)


def test_rejects_truncated_image(tmp_path: Path) -> None:
    truncated = tmp_path / "truncated.pyd"
    truncated.write_bytes(PEBuilder().add_export("PyInit_demo").build()[:0x50])

    with pytest.raises(PEFormatError):
        read_pe(truncated)


def test_unparseable_pe_yields_no_symbols(tmp_path: Path) -> None:
    """`read_symbols` mirrors nm's leniency instead of raising."""
    broken = tmp_path / "broken.dll"
    broken.write_bytes(b"MZ" + b"\x00" * 0x3A + b"\xff\xff\xff\x7f")

    assert read_symbols(broken).imports == ()
    assert read_symbols(broken).error is not None


def test_read_symbols_demangles_msvc_imports(tmp_path: Path) -> None:
    image = write_pe(
        tmp_path / "demo.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_import("torch_cpu.dll", AT_TENSOR_NUMEL)
        .add_import("torch_cpu.dll", STABLE_TENSOR_DIM),
    )

    symbols = read_symbols(image)

    # Exports stay raw: entry-point detection only needs the plain C name.
    assert symbols.exports == ("PyInit_demo",)
    assert any("at::Tensor::numel" in sym for sym in symbols.imports)
    assert any("torch::stable::Tensor::dim" in sym for sym in symbols.imports)
    # The public wrapper used by inspect.py takes the same route.
    assert extract_undefined_symbols(image) == list(symbols.imports)


def test_extension_detection_uses_export_table(tmp_path: Path) -> None:
    extension = write_pe(tmp_path / "demo.pyd", PEBuilder().add_export("PyInit_demo"))
    plugin = write_pe(
        tmp_path / "plugin.abi3.dll", PEBuilder().add_export("stable_torch_plugin")
    )

    assert is_extension_module(extension) is True
    # An abi3 filename alone is not enough — torch plugins use it too.
    assert is_extension_module(plugin) is False


def test_find_compiled_libraries_scopes_by_platform(tmp_path: Path) -> None:
    """A scan collects the host's formats, and only those.

    POSIX keeps the set it has always used, so adding a Windows DLL to a tree
    cannot change its verdict; Windows adds ``.dll`` next to ``.pyd``.
    """
    pkg = tmp_path / "pkg"
    write_pe(pkg / "a.dll", PEBuilder())
    write_pe(pkg / "b.pyd", PEBuilder())
    # Linker import libraries are archives, not PE images; they must not match.
    (pkg / "c.lib").write_bytes(b"!<arch>\n")

    found = {p.name for p in find_compiled_libraries(pkg)}
    if sys.platform == "win32":
        assert found == {"a.dll", "b.pyd"}
    else:
        assert found == {"b.pyd"}


def test_posix_scan_ignores_dll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Linux/macOS discovery rule must not change just because PE works.

    Reproduces the review case: a directory that gains a Windows DLL keeps its
    verdict, because the DLL is not part of a scan on this host. Naming the file
    explicitly still inspects it.
    """
    from torch_abi_audit import symbols

    monkeypatch.setattr(symbols, "LIBRARY_SUFFIXES", (".so", ".pyd", ".dylib"))
    pkg = tmp_path / "pkg"
    dll = write_pe(
        pkg / "libunstable.dll",
        PEBuilder().add_import("torch_cpu.dll", AT_TENSOR_NUMEL),
    )

    assert find_compiled_libraries(pkg) == []
    assert inspect_package(pkg).torch_verdict == "no-torch"

    # A path target is inspected whatever platform built the file.
    by_path = inspect_package(dll)
    assert [b.path.name for b in by_path.bundled_libs] == ["libunstable.dll"]
    assert by_path.torch_verdict == "torch-unstable"


# The builder lays the single section out right after the 0x200-byte headers and
# reserves the export directory first, so these are stable offsets into its data.
_SECTION_RAW = 0x200
_EXPORT_NUMBER_OF_NAMES = _SECTION_RAW + 24
_EXPORT_ADDRESS_OF_NAMES = _SECTION_RAW + 32


def _patch_image(path: Path, offset: int, value: int) -> None:
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, offset, value)
    path.write_bytes(bytes(data))


def test_implausible_export_count_is_rejected(tmp_path: Path) -> None:
    """The count comes from the image, so it is checked before anything is
    allocated — ``read_pe`` then degrades to "no exports" instead of raising."""
    image = write_pe(
        tmp_path / "demo.pyd",
        PEBuilder().add_export("PyInit_demo").add_import("torch_cpu.dll", AOTI_GET_DIM),
    )
    _patch_image(image, _EXPORT_NUMBER_OF_NAMES, 0xFFFFFFFF)

    with image.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        with pytest.raises(PEFormatError):
            pe._Image(m).exports([])

    data = read_pe(image)
    assert data.exports == ()
    assert data.imports == (AOTI_GET_DIM,)
    # The export table could not be read, so the result is not a clean scan.
    assert data.errors


def test_broken_export_directory_keeps_imports(tmp_path: Path) -> None:
    """A damaged export table must not throw the import table away — that would
    report a torch-using library as not using torch at all."""
    image = write_pe(
        tmp_path / "demo.pyd",
        PEBuilder().add_export("PyInit_demo").add_import("torch_cpu.dll", AOTI_GET_DIM),
    )
    # Name-pointer array points outside every section.
    _patch_image(image, _EXPORT_ADDRESS_OF_NAMES, 0xDEAD000)

    data = read_pe(image)

    assert data.imports == (AOTI_GET_DIM,)
    assert data.exports == ()
    assert data.errors


def test_damage_after_a_symbol_keeps_that_symbol(
    tmp_path: Path, builtin_parser_only: None
) -> None:
    """The failure mode that matters: one bad entry must not erase the good ones.

    An unstable import followed by an unreadable entry used to yield an empty
    import table, flipping the verdict to ``no-torch`` with nothing recorded.
    """
    builder = PEBuilder().add_import("torch_cpu.dll", AT_TENSOR_NUMEL)
    builder.add_import("torch_cpu.dll", AOTI_GET_DIM)
    image = write_pe(tmp_path / "demo.dll", builder)
    # Point the second thunk entry outside every section.
    _patch_image(image, builder.thunk_entry_offset(0, 1), 0xDEAD000)

    data = read_pe(image)

    assert data.imports == (AT_TENSOR_NUMEL,)
    assert data.errors
    # The recovered name still decides the torch verdict once demangled.
    symbols = read_symbols(image)
    assert symbols.incomplete
    verdict = torch_abi.classify_symbols(symbols.imports)
    assert verdict.uses_torch is True
    assert verdict.stable is False


def test_long_symbol_names_are_not_truncated(tmp_path: Path) -> None:
    """A name over the old fixed 4096-character cap is legal, not corruption."""
    long_name = "a" * 5000
    image = write_pe(
        tmp_path / "demo.dll", PEBuilder().add_import("torch_cpu.dll", long_name)
    )

    data = read_pe(image)

    assert data.imports == (long_name,)
    assert data.errors == ()


def test_over_cap_name_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    """The cap bounds the scan; exceeding it is damage, and damage is reported.

    Without this the only bounded-scan test would be the long-but-legal one, so
    a future tightening of the cap could make symbol tables disappear quietly.
    """
    builder = PEBuilder().add_import(
        "torch_cpu.dll", "c" * (pe._MAX_STRING_BYTES + 16)
    )
    image = write_pe(tmp_path / "demo.dll", builder)

    data = read_pe(image)

    assert data.imports == ()
    assert data.errors


def test_damaged_dll_name_does_not_lose_symbols(
    tmp_path: Path, builtin_parser_only: None
) -> None:
    """Reading the dependency name must not become a way to suppress imports.

    The name lives in the descriptor, so an unreadable ``Name`` field could
    abort the walk before any thunk was visited — reintroducing exactly the
    silent-truncation problem the per-entry recovery exists to prevent.
    """
    builder = PEBuilder().add_import("torch_cpu.dll", AT_TENSOR_NUMEL)
    image = write_pe(tmp_path / "demo.dll", builder)
    _patch_image(image, builder.import_descriptor_offset(0, "name"), 0xDEAD000)

    data = read_pe(image)

    assert data.imports == (AT_TENSOR_NUMEL,)
    assert data.libraries == ()
    assert data.errors


def test_damaged_delay_thunk_keeps_earlier_symbols(
    tmp_path: Path, builtin_parser_only: None
) -> None:
    builder = PEBuilder().add_delay_import("torch_cpu.dll", AOTI_GET_DIM)
    image = write_pe(tmp_path / "demo.dll", builder)
    _patch_image(image, builder.delay_thunk_entry_offset(0, 0), 0xDEAD000)

    data = read_pe(image)

    assert data.imports == ()
    assert data.errors
    # The dependency name still parsed, so abi3 classification keeps working.
    assert data.libraries == ("torch_cpu.dll",)


def test_builder_is_idempotent(tmp_path: Path) -> None:
    """Building twice must not stack the recorded offsets.

    Otherwise ``thunk_entry_offset`` addresses the first image while pointing
    into the second, silently damaging the wrong bytes.
    """
    builder = PEBuilder().add_import("torch_cpu.dll", AOTI_GET_DIM)
    first = builder.build()
    first_offsets = list(builder.thunk_rvas)
    second = builder.build()

    assert first == second
    assert builder.thunk_rvas == first_offsets


def test_import_libraries_are_reported(tmp_path: Path) -> None:
    image = write_pe(
        tmp_path / "demo.pyd",
        PEBuilder()
        .add_import("python3.dll", CPYTHON_STABLE)
        .add_import("torch_cpu.dll", AOTI_GET_DIM)
        .add_delay_import("KERNEL32.dll", "Sleep"),
    )

    data = read_pe(image)

    assert data.libraries == ("python3.dll", "torch_cpu.dll", "KERNEL32.dll")


def test_versioned_python_dll_is_not_abi3_compliant(tmp_path: Path) -> None:
    """Stable symbols are not enough on Windows.

    A build that links ``python314.dll`` carries the same stable names but is
    tied to one interpreter, so it is not a Stable ABI wheel.
    """
    image = write_pe(
        tmp_path / "demo.abi3.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_import("python314.dll", CPYTHON_STABLE),
    )

    report = inspect_package(image)
    extension = report.extensions[0]

    assert extension.cpython.violations == ()
    assert extension.cpython.python_dll == "python314.dll"
    assert extension.cpython.compliant is False
    assert report.cpython_verdict == "not-abi3"


def test_stable_python_dll_is_abi3_compliant(tmp_path: Path) -> None:
    image = write_pe(
        tmp_path / "demo.abi3.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_import("python3.dll", CPYTHON_STABLE),
    )

    report = inspect_package(image)
    extension = report.extensions[0]

    assert extension.cpython.python_dll == "python3.dll"
    assert extension.cpython.compliant is True
    assert report.cpython_verdict == "abi3-compliant"


def test_version_pinned_dll_fails_the_abi3_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reported gate failure: stable symbols, versioned DLL, exit 0 before.

    The package has to use torch, since the ``abi3`` policy is scoped to
    torch-using packages.
    """
    image = write_pe(
        tmp_path / "demo.abi3.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_import("python314.dll", CPYTHON_STABLE)
        .add_import("torch_cpu.dll", AOTI_GET_DIM),
    )

    assert main([str(image), "--check", "abi3"]) == 1
    assert "demo.abi3.pyd" in capsys.readouterr().err


def test_site_packages_top_level_file_uses_the_scan_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A library at the directory root follows the same rule as one in a package.

    Otherwise the same file is skipped inside ``pkg/`` but audited when it
    happens to sit next to it, so the scan result depends on layout.
    """
    from torch_abi_audit import symbols

    monkeypatch.setattr(symbols, "LIBRARY_SUFFIXES", (".so", ".pyd", ".dylib"))
    site_packages = tmp_path / "site-packages"
    write_pe(
        site_packages / "stray.dll",
        PEBuilder().add_import("torch_cpu.dll", AT_TENSOR_NUMEL),
    )
    assert inspect_site_packages(site_packages).packages == ()

    monkeypatch.setattr(symbols, "LIBRARY_SUFFIXES", (".pyd", ".dll"))
    assert [p.name for p in inspect_site_packages(site_packages).packages] == [
        "stray.dll"
    ]


def test_inspect_package_classifies_windows_libraries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extension vs bundled-library classification for PE files, on any host."""
    from torch_abi_audit import symbols

    monkeypatch.setattr(symbols, "LIBRARY_SUFFIXES", (".pyd", ".dll"))
    write_pe(
        tmp_path / "_demo.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_import("python3.dll", CPYTHON_UNSTABLE)
        .add_import("torch_cpu.dll", AT_TENSOR_NUMEL),
    )
    write_pe(
        tmp_path / "libaoti.dll",
        PEBuilder().add_import("torch_cpu.dll", AOTI_GET_DIM),
    )

    report = inspect_package(tmp_path)

    assert [e.path.name for e in report.extensions] == ["_demo.pyd"]
    assert [b.path.name for b in report.bundled_libs] == ["libaoti.dll"]


@pytest.fixture
def builtin_parser_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the built-in PE parser, so these tests don't depend on dumpbin.

    dumpbin reads a partially damaged image without complaint, which makes the
    recovery path unreachable; the point here is what the parser reports.
    """
    monkeypatch.setattr(symbols.dumpbin, "find_dumpbin", lambda: None)


def test_incomplete_read_is_reported_not_hidden(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], builtin_parser_only: None
) -> None:
    """The audit must not pass on a library it could only partly read.

    ``--check torch`` used to exit 0 here: the damaged entry erased the unstable
    import, so the package looked torch-free.
    """
    builder = PEBuilder().add_export("PyInit_demo")
    builder.add_import("torch_cpu.dll", AT_TENSOR_NUMEL)
    builder.add_import("torch_cpu.dll", AOTI_GET_DIM)
    image = write_pe(tmp_path / "demo.pyd", builder)
    _patch_image(image, builder.thunk_entry_offset(0, 1), 0xDEAD000)

    report = inspect_package(image)

    (extension,) = report.extensions
    assert extension.incomplete
    assert extension.error is None
    # The recovered symbol still drives the verdict...
    assert report.torch_verdict == "torch-unstable"
    # ...but the package is flagged, so the CLI reports an operational error.
    assert report.has_error is True

    assert main([str(image)]) == 2
    assert "inspection failed for" in capsys.readouterr().err


def test_incomplete_read_fails_the_ci_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], builtin_parser_only: None
) -> None:
    """Exit 2, not 0: an incomplete audit is an operational error, not a pass."""
    builder = PEBuilder()
    builder.add_import("torch_cpu.dll", AOTI_GET_DIM)
    builder.add_import("torch_cpu.dll", AT_TENSOR_NUMEL)
    image = write_pe(tmp_path / "demo.pyd", builder)
    _patch_image(image, builder.thunk_entry_offset(0, 1), 0xDEAD000)

    assert main([str(image), "--check", "both"]) == 2
    capsys.readouterr()
    # The verdict the gate would have used is still the recovered one.
    assert pe.read_pe(image).imports == (AOTI_GET_DIM,)


def test_relative_paths_do_not_alias_in_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache key is the resolved path, not the string the caller passed.

    Two directories can hold different, equally sized files written in the same
    timestamp tick; keying on a relative path made the second read return the
    first file's symbols.
    """
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    # Equal length, so the two images are byte-for-byte the same size.
    first = write_pe(
        first_dir / "demo.dll",
        PEBuilder().add_import("torch_cpu.dll", "aoti_torch_get_dim"),
    )
    second = write_pe(
        second_dir / "demo.dll",
        PEBuilder().add_import("python3.dll", "PyModule_Create2xxxx"),
    )
    stamp = first.stat()
    os.utime(second, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert first.stat().st_size == second.stat().st_size

    monkeypatch.chdir(first_dir)
    from_first = read_symbols(Path("demo.dll"))
    monkeypatch.chdir(second_dir)
    from_second = read_symbols(Path("demo.dll"))

    assert from_first.imports == ("aoti_torch_get_dim",)
    assert from_second.imports == ("PyModule_Create2xxxx",)
