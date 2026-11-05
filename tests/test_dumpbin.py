"""dumpbin backend: output parsing, and the prefer-then-fall-back contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pe_builder import PEBuilder, write_pe
from torch_abi_audit import dumpbin, pe, symbols

# Trimmed from real output: one regular block, one delay-load block, an
# ordinal-only import, descriptor rows and the trailing Summary section.
IMPORTS_TEXT = """Dump of file demo.dll

File Type: DLL

  Section contains the following imports:

    api-ms-win-core-rtlsupport-l1-1-0.dll
             18008BE80 Import Address Table
             1800B7558 Import Name Table
                     0 time date stamp
                     0 Index of first forwarder reference

                           5 RtlCompareMemory
                           D RtlRaiseException

    WS2_32.dll
             18000E108 Import Address Table
             18001E710 Import Name Table
                     0 time date stamp
                     0 Index of first forwarder reference

                             Ordinal    18

  Section contains the following delay load imports:

      UIAutomationCore.DLL
                00000001 Characteristics
        000000018072EFC0 Address of HMODULE
        000000018077DA78 Import Address Table
        0000000180709738 Import Name Table
        0000000180718838 Bound Import Name Table
        0000000000000000 Unload Import Name Table
                       0 time date stamp

                                      00000001801F1C2A    5A UiaProviderFromIAccessible
                                      00000001801F1C18    5D UiaRaiseAutomationEvent

  Summary

        1000 .data
        1000 .rdata
"""

# Trimmed from real output: header row, a plain export, a forwarded export
# (RVA column blank), ordinal-base metadata and the Summary section.
EXPORTS_TEXT = """Dump of file demo.dll

File Type: DLL

  Section contains the following exports for DEMO.dll

    00000000 characteristics
    1173227C time date stamp
        0.00 version
        255 ordinal base
        2001 number of functions

    ordinal hint RVA      name

        255    0 002237F0 PyInit_demo
        837    1          CLIPFORMAT_UserFree (forwarded to COMBASE.CLIPFORMAT_UserFree)

  Summary

        1000 .data
        86000 .text
"""


def test_parse_imports_reads_regular_and_delay_blocks() -> None:
    assert dumpbin.parse_imports(IMPORTS_TEXT) == (
        "RtlCompareMemory",
        "RtlRaiseException",
        "UiaProviderFromIAccessible",
        "UiaRaiseAutomationEvent",
    )


def test_parse_imports_reads_bound_delay_entries() -> None:
    """A bound delay-load entry carries two address columns, not one.

    Getting this wrong drops every bound entry silently — it undercounted
    ``ReAgent.dll`` by 114 imports, which is the direction that hides usage.
    """
    text = (
        "  Section contains the following delay load imports:\n"
        "\n"
        "    WIMGAPI.DLL\n"
        "              00000001 Characteristics\n"
        "      00000001800B4B50 Address of HMODULE\n"
        "                     0 time date stamp\n"
        "\n"
        "                  0000000180003000  0000000180003000     C WIMCreateFile\n"
        "                  0000000180003100  0000000180003100    48 WIMUnregisterMessageCallback\n"
        "                  0000000180003BD0  0000000180003BD0       Ordinal     6\n"
    )

    assert dumpbin.parse_imports(text) == (
        "WIMCreateFile",
        "WIMUnregisterMessageCallback",
    )


def test_parse_imports_skips_ordinals_descriptors_and_summary() -> None:
    names = dumpbin.parse_imports(IMPORTS_TEXT)
    assert "Ordinal" not in names
    assert "Characteristics" not in names
    assert ".data" not in names


def test_parse_exports_handles_plain_and_forwarded_entries() -> None:
    assert dumpbin.parse_exports(EXPORTS_TEXT) == (
        "PyInit_demo",
        "CLIPFORMAT_UserFree",
    )


def test_parse_libraries_from_import_blocks() -> None:
    """Dependency names, which the abi3 check needs and dumpbin prints as the
    block header line."""
    assert dumpbin.parse_libraries(IMPORTS_TEXT) == (
        "api-ms-win-core-rtlsupport-l1-1-0.dll",
        "WS2_32.dll",
        "UIAutomationCore.DLL",
    )


def test_parse_libraries_keeps_names_without_a_dll_suffix() -> None:
    """The built-in parser records whatever the descriptor names.

    ``PeerDistSh.dll`` imports from ``NETSH.EXE``; requiring a ``.dll`` suffix
    here would make the two backends disagree, and the dependency list now
    gates a compliance decision.
    """
    text = (
        "  Section contains the following imports:\n"
        "\n"
        "    NETSH.EXE\n"
        "             18000E108 Import Address Table\n"
        "\n"
        "                           5 RtlCompareMemory\n"
        "\n"
        "  Summary\n"
        "        1000 .data\n"
    )

    assert dumpbin.parse_libraries(text) == ("NETSH.EXE",)


def test_parse_outputs_are_empty_for_unrecognised_text() -> None:
    assert dumpbin.parse_imports("dumpbin: something went sideways\n") == ()
    assert dumpbin.parse_exports("dumpbin: something went sideways\n") == ()


def test_read_dumpbin_requires_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: None)
    with pytest.raises(dumpbin.DumpbinError):
        dumpbin.read_dumpbin(Path("whatever.dll"))


def test_read_dumpbin_reports_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(
        dumpbin.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1181, stdout="", stderr="boom"),
    )
    with pytest.raises(dumpbin.DumpbinError):
        dumpbin.read_dumpbin(Path("whatever.dll"))


@pytest.fixture
def pe_file(tmp_path: Path) -> Path:
    return write_pe(
        tmp_path / "demo.pyd",
        PEBuilder()
        .add_export("PyInit_demo")
        .add_import("torch_cpu.dll", "aoti_torch_get_dim"),
    )


def test_uses_dumpbin_when_available(
    monkeypatch: pytest.MonkeyPatch, pe_file: Path
) -> None:
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(
        dumpbin,
        "read_dumpbin",
        lambda path: dumpbin.DumpbinTables(
            imports=("torch_call_dispatcher",),
            exports=("PyInit_from_dumpbin",),
            libraries=("python3.dll",),
        ),
    )

    result = symbols._read_pe(pe_file)

    assert result.imports == ("torch_call_dispatcher",)
    assert result.exports == ("PyInit_from_dumpbin",)
    # The dependency list comes from dumpbin too, so the abi3 check still works.
    assert result.libraries == ("python3.dll",)


def test_uses_parser_when_dumpbin_is_absent(
    monkeypatch: pytest.MonkeyPatch, pe_file: Path
) -> None:
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: None)

    result = symbols._read_pe(pe_file)

    assert result.exports == ("PyInit_demo",)
    assert pe.read_pe(pe_file).imports == result.imports


def test_falls_back_when_dumpbin_fails(
    monkeypatch: pytest.MonkeyPatch, pe_file: Path
) -> None:
    def boom(path: Path) -> dumpbin.DumpbinTables:
        raise dumpbin.DumpbinError("nope")

    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(dumpbin, "read_dumpbin", boom)

    result = symbols._read_pe(pe_file)

    assert result.exports == ("PyInit_demo",)


def test_falls_back_when_dumpbin_yields_nothing(
    monkeypatch: pytest.MonkeyPatch, pe_file: Path
) -> None:
    """An empty dumpbin result is treated as a parse failure, not as a verdict."""
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(dumpbin, "read_dumpbin", lambda path: dumpbin.DumpbinTables())

    result = symbols._read_pe(pe_file)

    assert result.exports == ("PyInit_demo",)


def test_falls_back_when_dumpbin_omits_the_dependency_list(
    monkeypatch: pytest.MonkeyPatch, pe_file: Path
) -> None:
    """A missing dependency list would skip the ``python3XX.dll`` check.

    That is the same fail-open the fallback exists to prevent, so the result is
    only trusted when the libraries parsed as well.
    """
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(
        dumpbin,
        "read_dumpbin",
        lambda path: dumpbin.DumpbinTables(
            imports=("aoti_torch_get_dim",), exports=("PyInit_demo",), libraries=()
        ),
    )

    result = symbols._read_pe(pe_file)

    # Taken from the parser instead, which does report the dependency.
    assert result.libraries == ("torch_cpu.dll",)
    assert result.imports == ("aoti_torch_get_dim",)


def test_falls_back_when_dumpbin_misses_one_table(
    monkeypatch: pytest.MonkeyPatch, pe_file: Path
) -> None:
    """Half a dumpbin result is still a parse failure.

    If only ``/imports`` parsed (e.g. a reworded export table after a dumpbin
    upgrade), trusting it would leave ``exports`` empty, so entry-point
    detection would call the extension a bundled library.
    """
    monkeypatch.setattr(dumpbin, "find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(
        dumpbin,
        "read_dumpbin",
        lambda path: dumpbin.DumpbinTables(imports=("aoti_torch_get_dim",)),
    )

    result = symbols._read_pe(pe_file)

    assert result.exports == ("PyInit_demo",)
    assert "aoti_torch_get_dim" in result.imports


@pytest.mark.skipif(
    dumpbin.find_dumpbin() is None, reason="dumpbin is not on PATH"
)
def test_dumpbin_and_parser_agree_on_a_real_image(pe_file: Path) -> None:
    real = dumpbin.read_dumpbin(pe_file)
    ours = pe.read_pe(pe_file)

    assert real.imports == ours.imports
    assert real.exports == ours.exports
    assert real.libraries == ours.libraries
