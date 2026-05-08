"""High-level inspection helpers — the package's primary public API."""

from __future__ import annotations

import importlib.util
import sysconfig
from pathlib import Path

from . import cpython_abi, torch_abi
from .report import EnvironmentReport, ExtensionReport, PackageReport
from .symbols import (
    extract_undefined_symbols,
    find_compiled_libraries,
    is_extension_module,
)

_SKIP_SUFFIXES = (".dist-info", ".egg-info", ".data")
_SKIP_NAMES = ("__pycache__",)


def inspect_extension(path: Path) -> ExtensionReport:
    """Inspect a single extension module file."""
    path = Path(path).resolve()
    try:
        symbols = extract_undefined_symbols(path)
    except RuntimeError as exc:
        return ExtensionReport(
            path=path,
            cpython=cpython_abi.CPythonABIVerdict(intent=False, compliant=False),
            torch=torch_abi.TorchABIVerdict(uses_torch=False, stable=False),
            error=str(exc),
        )
    return ExtensionReport(
        path=path,
        cpython=cpython_abi.classify_symbols(symbols, path.name),
        torch=torch_abi.classify_symbols(symbols),
    )


def _resolve_import_name(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None:
        raise FileNotFoundError(f"cannot find package {name!r} on sys.path")
    locations = spec.submodule_search_locations
    if locations:
        return Path(next(iter(locations))).resolve()
    if spec.origin and spec.origin != "built-in":
        return Path(spec.origin).resolve()
    raise FileNotFoundError(f"{name!r} has no filesystem location")


def inspect_package(name_or_path: str | Path) -> PackageReport:
    """Inspect an installed package by import name, or a path to a file/directory."""
    target: Path
    name: str
    if isinstance(name_or_path, Path) or (
        isinstance(name_or_path, str) and ("/" in name_or_path or "\\" in name_or_path)
    ):
        p = Path(name_or_path).resolve()
        if not p.exists():
            return PackageReport(
                name=str(name_or_path),
                root=Path(name_or_path),
                error=f"path does not exist: {p}",
            )
        target = p
        name = p.name
    else:
        try:
            target = _resolve_import_name(str(name_or_path))
        except FileNotFoundError as exc:
            return PackageReport(
                name=str(name_or_path),
                root=Path(str(name_or_path)),
                error=str(exc),
            )
        name = str(name_or_path)

    if target.is_file():
        if not target.name.endswith((".so", ".pyd", ".dylib")):
            return PackageReport(
                name=name,
                root=target.parent,
                error=f"not a compiled library: {target}",
            )
        report = inspect_extension(target)
        if is_extension_module(target):
            return PackageReport(name=name, root=target.parent, extensions=(report,))
        return PackageReport(name=name, root=target.parent, bundled_libs=(report,))

    extensions, bundled = _split_libraries(target)
    return PackageReport(
        name=name, root=target, extensions=extensions, bundled_libs=bundled
    )


def _split_libraries(
    directory: Path,
) -> tuple[tuple[ExtensionReport, ...], tuple[ExtensionReport, ...]]:
    extensions: list[ExtensionReport] = []
    bundled: list[ExtensionReport] = []
    for p in find_compiled_libraries(directory):
        report = inspect_extension(p)
        (extensions if is_extension_module(p) else bundled).append(report)
    return tuple(extensions), tuple(bundled)


def _default_site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def inspect_site_packages(directory: Path | None = None) -> EnvironmentReport:
    """Inspect every package in a site-packages directory."""
    sp = Path(directory).resolve() if directory else _default_site_packages()
    if not sp.is_dir():
        raise NotADirectoryError(f"not a directory: {sp}")

    packages: list[PackageReport] = []
    for entry in sorted(sp.iterdir()):
        if entry.name in _SKIP_NAMES or entry.name.endswith(_SKIP_SUFFIXES):
            continue
        if entry.is_dir():
            extensions, bundled = _split_libraries(entry)
            if not extensions and not bundled:
                continue
            packages.append(
                PackageReport(
                    name=entry.name,
                    root=entry,
                    extensions=extensions,
                    bundled_libs=bundled,
                )
            )
        elif entry.is_file() and entry.name.endswith((".so", ".pyd", ".dylib")):
            report = inspect_extension(entry)
            if is_extension_module(entry):
                packages.append(
                    PackageReport(name=entry.name, root=sp, extensions=(report,))
                )
            else:
                packages.append(
                    PackageReport(name=entry.name, root=sp, bundled_libs=(report,))
                )
    return EnvironmentReport(site_packages=sp, packages=tuple(packages))
