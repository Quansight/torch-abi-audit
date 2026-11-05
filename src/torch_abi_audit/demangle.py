"""C++ symbol demangler, backed by pycxxfilt."""

from __future__ import annotations

import pycxxfilt


def demangle_symbol(name: str) -> str:
    """Demangle a single symbol; return the input unchanged if it can't be demangled.

    Itanium-ABI mangled C++ names start with ``_Z``; on Mach-O an extra leading
    underscore turns that into ``__Z``. PE/COFF C++ names on Windows use the
    MSVC scheme, which starts with ``?``. C symbols pass through unchanged. The
    GNU symbol-versioning suffix (``foo@GLIBCXX_3.4`` etc.) is handled by
    pycxxfilt itself (>= 1.2.0) and preserved in the output.

    pycxxfilt picks the mangling scheme from the prefix, so the same call
    handles all three; the prefix test here just avoids paying for a demangling
    attempt on plain C names.
    """
    if not name.startswith(("_Z", "__Z", "?")):
        return name
    try:
        out = pycxxfilt.demangle(name)
    except (ValueError, RuntimeError):
        return name
    return out or name
