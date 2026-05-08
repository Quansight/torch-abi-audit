"""torch-abi-audit: audit Python extensions for PyTorch (and CPython) Stable ABI compliance."""

from __future__ import annotations

from .cpython_abi import CPythonABIVerdict
from .inspect import inspect_extension, inspect_package, inspect_site_packages
from .report import EnvironmentReport, ExtensionReport, PackageReport
from .torch_abi import TorchABIVerdict

try:
    from ._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "CPythonABIVerdict",
    "EnvironmentReport",
    "ExtensionReport",
    "PackageReport",
    "TorchABIVerdict",
    "__version__",
    "inspect_extension",
    "inspect_package",
    "inspect_site_packages",
]
