"""C++ symbol demangler, backed by pycxxfilt."""

from __future__ import annotations

import pycxxfilt


def demangle_symbol(name: str) -> str:
    """Demangle a single symbol; return the input unchanged if it can't be demangled.

    Itanium-ABI mangled C++ names start with ``_Z``; on Mach-O an extra leading
    underscore turns that into ``__Z``. C symbols pass through unchanged. The
    GNU symbol-versioning suffix (``foo@GLIBCXX_3.4`` etc.) is split off
    because pycxxfilt rejects it as invalid input, then re-attached to the
    demangled output.
    """
    if not name.startswith(("_Z", "__Z")):
        return name
    base, _, version = name.partition("@")
    try:
        out = pycxxfilt.demangle(base)
    except (ValueError, RuntimeError):
        return name
    if not out:
        return name
    return f"{out}@{version}" if version else out
