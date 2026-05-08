"""Report data types and output formatters."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from .cpython_abi import CPythonABIVerdict
from .torch_abi import TorchABIVerdict


@dataclass(frozen=True, slots=True)
class ExtensionReport:
    """Per-extension-module result."""

    path: Path
    cpython: CPythonABIVerdict
    torch: TorchABIVerdict
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PackageReport:
    """Result for one installed package (or one path the user pointed at).

    ``extensions`` holds Python extension modules (``PyInit_*`` defined).
    ``bundled_libs`` holds other compiled shared libraries shipped in the
    package — internal libtorch wrappers, torch plugins loaded via
    ``STABLE_TORCH_LIBRARY``, etc. Both contribute to the torch ABI verdict;
    only ``extensions`` are considered for the CPython ABI verdict (the
    limited-API rules don't apply to libraries that aren't loaded by Python's
    import system).
    """

    name: str
    root: Path
    extensions: tuple[ExtensionReport, ...] = ()
    bundled_libs: tuple[ExtensionReport, ...] = ()
    error: str | None = None

    @property
    def _all_libs(self) -> tuple[ExtensionReport, ...]:
        return (*self.extensions, *self.bundled_libs)

    @property
    def torch_verdict(self) -> str:
        """Worst-case roll-up across extensions AND bundled libraries.

        Bundled libs matter because torch and torchcodec keep their unstable
        libtorch usage in non-extension shared objects (libtorch_python.so,
        libtorchcodec_core*.so); ignoring those would hide the verdict.
        """
        if self.error:
            return "error"
        libs = self._all_libs
        if any(e.error for e in libs):
            return "error"
        if any(not e.torch.stable and e.torch.uses_torch for e in libs):
            return "torch-unstable"
        if any(e.torch.stable for e in libs):
            return "torch-stable"
        return "no-torch"

    @property
    def cpython_verdict(self) -> str:
        """Roll-up of CPython Stable ABI status. ``mixed`` means at least one
        extension is compliant and at least one isn't."""
        if not self.extensions:
            return "no-extensions"
        compliant = [e.cpython.compliant for e in self.extensions]
        if all(compliant):
            return "abi3-compliant"
        if not any(compliant):
            return "not-abi3"
        return "mixed"


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    """Result for a whole site-packages directory."""

    site_packages: Path
    packages: tuple[PackageReport, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Formatters

class _ReportEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Path):
            return str(o)
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        return super().default(o)


def format_json(report: ExtensionReport | PackageReport | EnvironmentReport) -> str:
    return json.dumps(report, cls=_ReportEncoder, indent=2)


# Visual labels reused by the table formatter.
_TORCH_LABEL = {
    "torch-stable": "STABLE",
    "torch-unstable": "UNSTABLE",
    "no-torch": "NO-TORCH",
    "error": "ERROR",
}

_CPY_LABEL = {
    "abi3-compliant": "abi3",
    "not-abi3": "no",
    "mixed": "mixed",
    "no-extensions": "n/a",
}


def _cpython_label(verdict: CPythonABIVerdict) -> str:
    """Per-row CPython ABI label for the human-readable table.

    Distinguishes between an extension with concrete violations vs. one whose
    filename carries an ``abi3`` tag but doesn't reference the CPython C API
    at all (e.g. a torch plugin loaded via ``STABLE_TORCH_LIBRARY``).
    """
    if verdict.compliant:
        return "abi3-ok"
    if verdict.violations:
        return "abi3-tagged-violations" if verdict.intent else "uses-private-api"
    if verdict.intent:
        return "abi3-tagged-no-capi"
    return "not-abi3"


def _format_extension_lines(ext: ExtensionReport, root: Path, verbose: bool) -> list[str]:
    rel = ext.path.relative_to(root) if root in ext.path.parents or root == ext.path else ext.path
    if ext.error:
        return [f"    [error]    {rel}  ({ext.error})"]
    torch_label = _torch_label_for_extension(ext)
    cpy_label = _cpython_label(ext.cpython)
    line = f"    [{torch_label:<8}] [{cpy_label:<22}] {rel}"
    if ext.torch.uses_torch:
        line += f"  (stable_shim={ext.torch.stable_shim_count}, unstable={len(ext.torch.unstable_symbols)})"
    out = [line]
    if verbose:
        for s in ext.torch.unstable_symbols[:15]:
            out.append(f"        torch unstable: {s}")
        if len(ext.torch.unstable_symbols) > 15:
            out.append(f"        ... {len(ext.torch.unstable_symbols) - 15} more")
        for s in ext.cpython.violations[:15]:
            out.append(f"        cpython violation: {s}")
        if len(ext.cpython.violations) > 15:
            out.append(f"        ... {len(ext.cpython.violations) - 15} more")
    return out


def _torch_label_for_extension(ext: ExtensionReport) -> str:
    if ext.error:
        return "ERROR"
    if not ext.torch.uses_torch:
        return "NO-TORCH"
    return "STABLE" if ext.torch.stable else "UNSTABLE"


def format_package_table(report: PackageReport, *, verbose: bool = False) -> str:
    lines = [
        f"Package: {report.name}",
        f"  Root: {report.root}",
        f"  Torch ABI:   {_TORCH_LABEL.get(report.torch_verdict, report.torch_verdict)}",
        f"  CPython ABI: {_CPY_LABEL.get(report.cpython_verdict, report.cpython_verdict)}",
        f"  Extensions:  {len(report.extensions)}",
        f"  Bundled libs: {len(report.bundled_libs)}",
    ]
    if report.error:
        lines.append(f"  Error: {report.error}")
    if report.extensions:
        lines.append("  -- extensions --")
        for ext in report.extensions:
            lines.extend(_format_extension_lines(ext, report.root, verbose))
    if report.bundled_libs:
        lines.append("  -- bundled libs --")
        for ext in report.bundled_libs:
            lines.extend(_format_extension_lines(ext, report.root, verbose))
    return "\n".join(lines)


def format_environment_table(
    report: EnvironmentReport, *, verbose: bool = False, show_all: bool = False
) -> str:
    rows: list[tuple[str, str, str, int, int]] = []
    for pkg in report.packages:
        torch_v = pkg.torch_verdict
        if not show_all and torch_v == "no-torch":
            continue
        rows.append((
            pkg.name,
            _TORCH_LABEL.get(torch_v, torch_v),
            _CPY_LABEL.get(pkg.cpython_verdict, pkg.cpython_verdict),
            len(pkg.extensions),
            len(pkg.bundled_libs),
        ))
    if not rows:
        return f"Site-packages: {report.site_packages}\n  (no packages with libtorch use found; pass --all to list everything)"

    name_w = max(len(r[0]) for r in rows)
    name_w = max(min(name_w, 40), 16)

    out = [f"Site-packages: {report.site_packages}", ""]
    out.append(f"  {'PACKAGE':<{name_w}}  {'TORCH':<8}  {'CPYTHON':<8}  EXTS  BUNDLED")
    out.append(f"  {'-' * name_w}  {'-' * 8}  {'-' * 8}  ----  -------")
    # Sort: unstable/error first, then stable, then no-torch.
    order = {"UNSTABLE": 0, "ERROR": 1, "STABLE": 2, "NO-TORCH": 3}
    rows.sort(key=lambda r: (order.get(r[1], 99), r[0]))
    for name, torch_v, cpy_v, n_ext, n_bundled in rows:
        display_name = name if len(name) <= name_w else name[: name_w - 1] + "…"
        out.append(
            f"  {display_name:<{name_w}}  {torch_v:<8}  {cpy_v:<8}  {n_ext:>4}  {n_bundled:>7}"
        )

    if verbose:
        out.append("")
        for pkg in report.packages:
            if pkg.torch_verdict in ("torch-unstable", "error"):
                out.append("")
                out.append(format_package_table(pkg, verbose=True))

    return "\n".join(out)
