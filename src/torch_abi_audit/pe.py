"""PE/COFF (Windows ``.pyd`` / ``.dll``) import and export table parsing.

Windows binaries have no equivalent of ELF's dynamic symbol table. The two
signals this package needs come from the load-time headers instead:

* the **import directory** lists, per DLL, every symbol the image references
  from outside itself — the PE counterpart of ``nm -uD`` — together with the
  names of those DLLs, which is how a Stable ABI extension is distinguished
  from a version-pinned one;
* the **export directory** lists the names the image makes available, which is
  where Python's ``PyInit_*`` hook lives.

Shipped PE images usually have their COFF symbol table stripped, so ``nm``
reports "no symbols" for them; the import/export tables are always present.
Parsing them directly keeps Windows working without ``dumpbin`` (or any other
external tool) and lets Windows wheels be audited from any host OS.

Names are returned exactly as stored in the image: undecorated C names carry no
``__imp_`` prefix and no Mach-O leading underscore, and C++ names are
MSVC-mangled (``?name@scope@@...``) for :mod:`.demangle` to handle.

A damaged directory costs only the names that come after the damage: the walks
append as they go, so callers keep whatever was recovered and get a message in
:attr:`PEImageData.errors` saying the result is incomplete. Dropping a whole
table would report a torch-using library as using no torch at all, which is
both wrong and the easiest way for a malformed image to hide.
"""

from __future__ import annotations

import mmap
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_PE32_MAGIC = 0x10B
_PE32_PLUS_MAGIC = 0x20B

_IMPORT_DESCRIPTOR_SIZE = 20
_DELAY_DESCRIPTOR_SIZE = 32

#: ``grAttrs`` bit 0 of a delay-load descriptor means its fields are RVAs
#: rather than virtual addresses (the format MSVC has emitted for a long time).
_DELAY_RVA_BASED = 0x1

#: Guard against pathological descriptor tables; real images have a handful.
_MAX_DESCRIPTORS = 1 << 16

#: Cap on a single symbol name. Generous enough for legitimate long names (a
#: test covers 5000 characters) while keeping every scan bounded: without it a
#: crafted image can point many entries at a region whose first NUL is near the
#: end of the file, turning one audit into quadratic work and memory.
_MAX_STRING_BYTES = 1 << 16

#: Export name cap. Much larger than :data:`_MAX_DESCRIPTORS` because a single
#: library can legitimately export tens of thousands of C++ symbols — torch's
#: ``torch_cpu.dll`` exports ~60k. The file-size check in :meth:`_Image.exports`
#: is the tight bound; this one only stops a crafted count from driving a huge
#: allocation.
_MAX_EXPORT_NAMES = 1 << 20


class PEFormatError(ValueError):
    """The file is not a structurally valid, parseable PE image."""


@dataclass(frozen=True, slots=True)
class PEImageData:
    """Everything read out of one PE image.

    ``imports`` holds the referenced symbol names (regular and delay-load
    tables, in image order), ``exports`` the defined names, and ``libraries``
    the DLLs those imports come from. Any entry in ``errors`` means the
    corresponding directory could not be followed to its end, so the names
    gathered from it are incomplete — but they are still the names that were
    recovered before the failure.
    """

    imports: tuple[str, ...] = ()
    exports: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class _Image:
    """Header state of one mapped PE image: sections and data directories."""

    def __init__(self, buf: mmap.mmap) -> None:
        self._buf = buf
        self._size = len(buf)
        if self._read(0, 2) != b"MZ":
            raise PEFormatError("missing MZ header")
        coff = self.u32(0x3C) + 4  # e_lfanew points at "PE\0\0"
        if self._read(coff - 4, 4) != b"PE\0\0":
            raise PEFormatError("missing PE signature")
        n_sections = self.u16(coff + 2)
        optional_size = self.u16(coff + 16)
        optional = coff + 20
        magic = self.u16(optional)
        if magic == _PE32_MAGIC:
            self.pe32 = True
            self.image_base = self.u32(optional + 28)
            self._n_dirs = self.u32(optional + 92)
            self._dirs_offset = optional + 96
        elif magic == _PE32_PLUS_MAGIC:
            self.pe32 = False
            self.image_base = self.u64(optional + 24)
            self._n_dirs = self.u32(optional + 108)
            self._dirs_offset = optional + 112
        else:
            raise PEFormatError(f"unsupported optional header magic {magic:#x}")
        self._sections: list[tuple[int, int, int, int]] = []
        section_table = optional + optional_size
        for i in range(n_sections):
            base = section_table + 40 * i
            self._sections.append((
                self.u32(base + 12),  # VirtualAddress
                self.u32(base + 8),  # VirtualSize
                self.u32(base + 16),  # SizeOfRawData
                self.u32(base + 20),  # PointerToRawData
            ))

    # -- raw reads ---------------------------------------------------------

    def _read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self._size:
            raise PEFormatError(f"read of {size} bytes at {offset:#x} is out of bounds")
        return bytes(self._buf[offset : offset + size])

    def u16(self, offset: int) -> int:
        return struct.unpack("<H", self._read(offset, 2))[0]

    def u32(self, offset: int) -> int:
        return struct.unpack("<I", self._read(offset, 4))[0]

    def u64(self, offset: int) -> int:
        return struct.unpack("<Q", self._read(offset, 8))[0]

    def cstring(self, offset: int) -> str:
        """NUL-terminated ASCII-ish string at ``offset`` (PE names are bytes).

        The scan is bounded by :data:`_MAX_STRING_BYTES` rather than a few
        thousand characters: names over the old 4096 limit are unusual but
        legal, and rejecting them turned a readable table into a parse failure.
        Anything longer than the cap is not a symbol name, so it is reported as
        damage instead.
        """
        if offset < 0 or offset >= self._size:
            raise PEFormatError(f"string offset {offset:#x} is out of bounds")
        end = min(offset + _MAX_STRING_BYTES, self._size)
        nul = self._buf.find(b"\x00", offset, end)
        if nul < 0:
            raise PEFormatError(f"unterminated string at {offset:#x}")
        return bytes(self._buf[offset:nul]).decode("latin-1")

    # -- addressing --------------------------------------------------------

    def directory(self, index: int) -> tuple[int, int]:
        """``(rva, size)`` of data directory ``index``; ``(0, 0)`` if absent."""
        if index >= self._n_dirs:
            return (0, 0)
        offset = self._dirs_offset + 8 * index
        rva = self.u32(offset)
        if not rva:
            return (0, 0)
        return rva, self.u32(offset + 4)

    def rva_to_offset(self, rva: int) -> int:
        """File offset backing ``rva``."""
        for va, vsize, raw_size, raw_offset in self._sections:
            if va <= rva < va + max(vsize, raw_size, 1):
                delta = rva - va
                if delta >= raw_size:
                    # e.g. .bss: mapped at load time but absent from the file.
                    raise PEFormatError(f"rva {rva:#x} has no file backing")
                return raw_offset + delta
        raise PEFormatError(f"rva {rva:#x} is not inside any section")

    # -- tables ------------------------------------------------------------

    def imports(self, out: list[str], libraries: list[str], errors: list[str]) -> None:
        """Named symbols from the import directory (ordinal-only entries are skipped).

        ``libraries`` receives the DLL each descriptor names, which is how a
        Stable ABI extension is told apart from one pinned to ``python3XX.dll``.
        """
        rva, _ = self.directory(1)
        if not rva:
            return
        offset = self.rva_to_offset(rva)
        for _ in range(_MAX_DESCRIPTORS):
            fields = struct.unpack("<5I", self._read(offset, _IMPORT_DESCRIPTOR_SIZE))
            if not any(fields):
                break
            # OriginalFirstThunk (bound at build time) wins over FirstThunk,
            # which the loader overwrites with resolved addresses.
            thunk_rva = fields[0] or fields[4]
            self._note_dll(fields[3], libraries, errors)
            if thunk_rva:
                self._thunk_names(thunk_rva, out)
            offset += _IMPORT_DESCRIPTOR_SIZE

    def delay_imports(
        self, out: list[str], libraries: list[str], errors: list[str]
    ) -> None:
        """Named symbols from the delay-load import directory."""
        rva, _ = self.directory(13)
        if not rva:
            return
        offset = self.rva_to_offset(rva)
        for _ in range(_MAX_DESCRIPTORS):
            fields = struct.unpack("<8I", self._read(offset, _DELAY_DESCRIPTOR_SIZE))
            if not any(fields):
                break
            attrs, dll_rva, _handle, iat, name_table = fields[:5]
            if dll_rva:
                if not attrs & _DELAY_RVA_BASED:
                    dll_rva -= self.image_base  # pre-VS6 descriptors hold VAs
                self._note_dll(dll_rva, libraries, errors)
            thunk = name_table or iat
            if thunk:
                if not attrs & _DELAY_RVA_BASED:
                    thunk -= self.image_base
                self._thunk_names(thunk, out)
            offset += _DELAY_DESCRIPTOR_SIZE

    def _note_dll(self, rva: int, libraries: list[str], errors: list[str]) -> None:
        """Record a dependency name, or note it without losing the symbols.

        Catching locally (rather than letting the walk abort) is what keeps a
        damaged ``Name`` field from costing this descriptor's symbols and every
        descriptor after it.
        """
        try:
            libraries.append(self.cstring(self.rva_to_offset(rva)))
        except PEFormatError as exc:
            errors.append(f"import DLL name: {exc}")

    def exports(self, out: list[str]) -> None:
        """Names from the export directory.

        ``NumberOfNames`` comes straight from the image, and unlike the other
        table walks its loop bound is not implied by hitting the end of the
        file, so check both the sanity cap and that the name-pointer array fits
        inside the image before allocating anything.
        """
        rva, _ = self.directory(0)
        if not rva:
            return
        offset = self.rva_to_offset(rva)
        n_names = self.u32(offset + 24)
        names_rva = self.u32(offset + 32)
        if not n_names or not names_rva:
            return
        table = self.rva_to_offset(names_rva)
        if n_names > _MAX_EXPORT_NAMES or table + 4 * n_names > self._size:
            raise PEFormatError(
                f"export name table of {n_names} entries does not fit the image"
            )
        for i in range(n_names):
            out.append(self.cstring(self.rva_to_offset(self.u32(table + 4 * i))))

    def _thunk_names(self, rva: int, out: list[str]) -> None:
        """Walk one thunk table, appending the hint/name of each named entry."""
        width = 4 if self.pe32 else 8
        fmt = "<I" if self.pe32 else "<Q"
        ordinal_flag = 1 << (31 if self.pe32 else 63)
        offset = self.rva_to_offset(rva)
        for _ in range(_MAX_DESCRIPTORS):
            (entry,) = struct.unpack(fmt, self._read(offset, width))
            if entry == 0:
                break
            if not entry & ordinal_flag:
                # Entry is the RVA of an IMAGE_IMPORT_BY_NAME: u16 hint, then name.
                name_offset = self.rva_to_offset(entry & (ordinal_flag - 1))
                out.append(self.cstring(name_offset + 2))
            offset += width


def _guard(
    errors: list[str],
    label: str,
    read: Callable[..., None],
    *args: list[str],
) -> None:
    """Run one directory walk, keeping what it recovered and noting any failure."""
    try:
        read(*args)
    except PEFormatError as exc:
        errors.append(f"{label} directory: {exc}")


def read_pe(path: Path) -> PEImageData:
    """Read the PE image at ``path``.

    A directory that cannot be followed to its end is recorded in
    :attr:`PEImageData.errors` while the names recovered from it are kept, so a
    malformed image cannot hide its references by damaging one entry. Header
    damage still fails the whole file with :class:`PEFormatError`.
    """
    imports: list[str] = []
    exports: list[str] = []
    libraries: list[str] = []
    errors: list[str] = []
    try:
        with path.open("rb") as f, mmap.mmap(
            f.fileno(), 0, access=mmap.ACCESS_READ
        ) as mapped:
            image = _Image(mapped)
            _guard(errors, "import", image.imports, imports, libraries, errors)
            _guard(
                errors,
                "delay-load import",
                image.delay_imports,
                imports,
                libraries,
                errors,
            )
            _guard(errors, "export", image.exports, exports)
    except PEFormatError:
        raise
    except (OSError, ValueError, struct.error) as exc:
        # Empty files make mmap raise ValueError; the rest are I/O problems and
        # any residual structural surprise from a crafted image.
        raise PEFormatError(f"cannot parse {path}: {exc}") from exc
    return PEImageData(
        imports=tuple(imports),
        exports=tuple(exports),
        libraries=tuple(dict.fromkeys(libraries)),
        errors=tuple(errors),
    )
