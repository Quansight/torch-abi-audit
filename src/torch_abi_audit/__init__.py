"""torch-abi-audit: audit Python extensions for PyTorch (and CPython) Stable ABI compliance."""

from __future__ import annotations

from .cpython_abi import CPythonABIVerdict
from .inspect import inspect_extension, inspect_package, inspect_site_packages
from .report import EnvironmentReport, ExtensionReport, PackageReport
from .torch_abi import TorchABIVerdict
from .torch_versions import (
    BASELINE_VERSION,
    minimum_version,
    symbol_version,
)

try:
    from ._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "BASELINE_VERSION",
    "CPythonABIVerdict",
    "EnvironmentReport",
    "ExtensionReport",
    "PackageReport",
    "TorchABIVerdict",
    "__version__",
    "inspect_extension",
    "inspect_package",
    "inspect_site_packages",
    "minimum_version",
    "symbol_version",
]
