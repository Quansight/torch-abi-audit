"""Build minimal PE images in memory, so PE parsing can be tested on any OS.

Only the structures :mod:`torch_abi_audit.pe` reads are populated: the header
chain, the section table, and the import / delay-import / export directories.
Everything else is zeroed, which is fine because nothing here is loaded by
Windows.
"""

from __future__ import annotations

import struct
from pathlib import Path

_SECTION_RVA = 0x1000
_RAW_POINTER = 0x200
_HEADER_SIZE = 0x200
_FILE_ALIGNMENT = 0x200
_IMAGE_BASE = {True: 0x1_8000_0000, False: 0x1000_0000}


def _reserve(section: bytearray, size: int) -> int:
    """Reserve ``size`` zero bytes, returning the section offset of the block."""
    offset = len(section)
    section.extend(b"\x00" * size)
    return offset


def _append(section: bytearray, data: bytes) -> int:
    """Append ``data``, returning the RVA it will have."""
    rva = _SECTION_RVA + len(section)
    section.extend(data)
    return rva


def _align(section: bytearray, alignment: int) -> None:
    section.extend(b"\x00" * (-len(section) % alignment))


class PEBuilder:
    """Assemble a one-section PE32 / PE32+ image with import and export tables."""

    def __init__(self, *, pe32_plus: bool = True) -> None:
        self.pe32_plus = pe32_plus
        self.exports: list[str] = []
        #: ``(dll, name)``; ``name is None`` means an ordinal-only import.
        self.imports: list[tuple[str, str | None]] = []
        #: ``(dll, name, rva_based)``.
        self.delay_imports: list[tuple[str, str, bool]] = []
        #: RVAs of each import group's thunk array, in descriptor order. Reset
        #: by :meth:`build`, so they always describe the most recent image.
        self.thunk_rvas: list[int] = []
        #: RVAs of each delay-load group's thunk array, likewise per build.
        self.delay_thunk_rvas: list[int] = []
        #: File offsets of each import descriptor, for damaging individual ones.
        self.import_descriptor_offsets: list[int] = []

    def file_offset(self, rva: int) -> int:
        """File offset of ``rva`` in these single-section images."""
        return rva - _SECTION_RVA + _RAW_POINTER

    def thunk_entry_offset(self, group: int, entry: int) -> int:
        """File offset of one thunk entry, for tests that damage the table."""
        width = 8 if self.pe32_plus else 4
        return self.file_offset(self.thunk_rvas[group]) + entry * width

    def delay_thunk_entry_offset(self, group: int, entry: int) -> int:
        """File offset of one delay-load thunk entry, for damage-based tests."""
        width = 8 if self.pe32_plus else 4
        return self.file_offset(self.delay_thunk_rvas[group]) + entry * width

    def import_descriptor_offset(self, group: int, field: str) -> int:
        """File offset of one field of an import descriptor.

        ``field`` is ``"thunk"`` (OriginalFirstThunk) or ``"name"`` (the DLL
        name RVA), the two the tests damage.
        """
        offsets = {"thunk": 0, "name": 12}
        return self.import_descriptor_offsets[group] + offsets[field]

    # -- authoring ---------------------------------------------------------

    def add_export(self, name: str) -> PEBuilder:
        self.exports.append(name)
        return self

    def add_import(self, dll: str, name: str | None) -> PEBuilder:
        self.imports.append((dll, name))
        return self

    def add_delay_import(
        self, dll: str, name: str, *, rva_based: bool = True
    ) -> PEBuilder:
        self.delay_imports.append((dll, name, rva_based))
        return self

    # -- assembly ----------------------------------------------------------

    def build(self) -> bytes:
        # Reset the recorded layouts: building twice (e.g. build, add_import,
        # build again) must not leave the earlier image's offsets at index 0.
        self.thunk_rvas.clear()
        self.delay_thunk_rvas.clear()
        self.import_descriptor_offsets.clear()
        section = bytearray()
        export_dir = _reserve(section, 40) if self.exports else None
        groups = self._grouped_imports()
        import_dir = (
            _reserve(section, 20 * (len(groups) + 1)) if groups else None
        )
        delay_dir = (
            _reserve(section, 32 * (len(self.delay_imports) + 1))
            if self.delay_imports
            else None
        )
        if export_dir is not None:
            self._write_exports(section, export_dir)
        if import_dir is not None:
            self._write_imports(section, import_dir, groups)
        if delay_dir is not None:
            self._write_delay_imports(section, delay_dir)

        virtual_size = len(section)
        section.extend(b"\x00" * (-len(section) % _FILE_ALIGNMENT))
        header = self._header(
            virtual_size=virtual_size,
            raw_size=len(section),
            export_dir=export_dir,
            import_dir=import_dir,
            delay_dir=delay_dir,
        )
        return header + bytes(section)

    def _grouped_imports(self) -> list[tuple[str, list[str | None]]]:
        groups: dict[str, list[str | None]] = {}
        for dll, name in self.imports:
            groups.setdefault(dll, []).append(name)
        return list(groups.items())

    def _write_exports(self, section: bytearray, at: int) -> None:
        dll_name = _append(section, b"fixture.dll\x00")
        name_rvas = [
            _append(section, name.encode("ascii") + b"\x00") for name in self.exports
        ]
        _align(section, 4)
        functions = _append(section, b"\x00" * (4 * len(self.exports)))
        names = _append(
            section, b"".join(struct.pack("<I", rva) for rva in name_rvas)
        )
        ordinals = _append(
            section,
            b"".join(struct.pack("<H", i) for i in range(len(self.exports))),
        )
        struct.pack_into(
            "<IIHHIIIIIII",
            section,
            at,
            0,  # Characteristics
            0,  # TimeDateStamp
            0,  # MajorVersion
            0,  # MinorVersion
            dll_name,
            1,  # Base
            len(self.exports),  # NumberOfFunctions
            len(self.exports),  # NumberOfNames
            functions,
            names,
            ordinals,
        )

    def _write_imports(
        self,
        section: bytearray,
        at: int,
        groups: list[tuple[str, list[str | None]]],
    ) -> None:
        for index, (dll, names) in enumerate(groups):
            dll_rva = _append(section, dll.encode("ascii") + b"\x00")
            thunks = [self._import_thunk(section, name) for name in names]
            _align(section, 8 if self.pe32_plus else 4)
            thunk_rva = self._write_thunks(section, thunks)
            self.thunk_rvas.append(thunk_rva)
            self.import_descriptor_offsets.append(_RAW_POINTER + at + 20 * index)
            struct.pack_into(
                "<IIIII",
                section,
                at + 20 * index,
                thunk_rva,  # OriginalFirstThunk
                0,  # TimeDateStamp
                0,  # ForwarderChain
                dll_rva,  # Name
                thunk_rva,  # FirstThunk
            )

    def _write_delay_imports(self, section: bytearray, at: int) -> None:
        for index, (dll, name, rva_based) in enumerate(self.delay_imports):
            dll_rva = _append(section, dll.encode("ascii") + b"\x00")
            thunk = self._import_thunk(section, name)
            _align(section, 8 if self.pe32_plus else 4)
            thunk_rva = self._write_thunks(section, [thunk])
            self.delay_thunk_rvas.append(thunk_rva)
            base = 0 if rva_based else _IMAGE_BASE[self.pe32_plus]
            struct.pack_into(
                "<8I",
                section,
                at + 32 * index,
                1 if rva_based else 0,  # grAttrs
                dll_rva + base,
                0,  # ModuleHandleRVA
                thunk_rva + base,  # ImportAddressTableRVA
                thunk_rva + base,  # ImportNameTableRVA
                0,  # BoundImportAddressTableRVA
                0,  # UnloadImportAddressTableRVA
                0,  # TimeDateStamp
            )

    def _import_thunk(self, section: bytearray, name: str | None) -> int | None:
        if name is None:
            return None  # ordinal-only entry
        # IMAGE_IMPORT_BY_NAME is a u16 hint followed by the NUL-terminated name.
        return _append(section, b"\x00\x00" + name.encode("ascii") + b"\x00")

    def _write_thunks(self, section: bytearray, thunks: list[int | None]) -> int:
        width = 8 if self.pe32_plus else 4
        fmt = "<Q" if self.pe32_plus else "<I"
        ordinal = 1 << (63 if self.pe32_plus else 31)
        entries = b"".join(
            struct.pack(fmt, ordinal if thunk is None else thunk) for thunk in thunks
        )
        return _append(section, entries + b"\x00" * width)

    def _header(
        self,
        *,
        virtual_size: int,
        raw_size: int,
        export_dir: int | None,
        import_dir: int | None,
        delay_dir: int | None,
    ) -> bytes:
        optional_size = 240 if self.pe32_plus else 224
        header = bytearray(_HEADER_SIZE)
        header[0:2] = b"MZ"
        struct.pack_into("<I", header, 0x3C, 0x40)  # e_lfanew
        header[0x40:0x44] = b"PE\x00\x00"
        struct.pack_into(
            "<HHIIIHH",
            header,
            0x44,
            0x8664 if self.pe32_plus else 0x14C,  # Machine
            1,  # NumberOfSections
            0,  # TimeDateStamp
            0,  # PointerToSymbolTable
            0,  # NumberOfSymbols
            optional_size,
            0x2022,  # Characteristics: DLL | executable | large address aware
        )
        optional = 0x44 + 20
        if self.pe32_plus:
            struct.pack_into("<H", header, optional, 0x20B)
            struct.pack_into("<Q", header, optional + 24, _IMAGE_BASE[True])
            struct.pack_into("<I", header, optional + 108, 16)
            directories = optional + 112
        else:
            struct.pack_into("<H", header, optional, 0x10B)
            struct.pack_into("<I", header, optional + 28, _IMAGE_BASE[False])
            struct.pack_into("<I", header, optional + 92, 16)
            directories = optional + 96
        struct.pack_into("<I", header, optional + 32, 0x1000)  # SectionAlignment
        struct.pack_into("<I", header, optional + 36, _FILE_ALIGNMENT)
        struct.pack_into(
            "<I", header, optional + 56, _SECTION_RVA + raw_size  # SizeOfImage
        )
        struct.pack_into("<I", header, optional + 60, _HEADER_SIZE)  # SizeOfHeaders
        for index, block in ((0, export_dir), (1, import_dir), (13, delay_dir)):
            if block is not None:
                struct.pack_into(
                    "<II", header, directories + 8 * index, _SECTION_RVA + block, 0x100
                )

        table = optional + optional_size
        header[table : table + 8] = b".rdata\x00\x00"
        struct.pack_into(
            "<IIII",
            header,
            table + 8,
            virtual_size,
            _SECTION_RVA,
            raw_size,
            _RAW_POINTER,
        )
        struct.pack_into("<I", header, table + 36, 0x40000040)
        return bytes(header)


def write_pe(path: Path, builder: PEBuilder) -> Path:
    """Build ``builder`` and write it to ``path`` (directories are created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(builder.build())
    return path
