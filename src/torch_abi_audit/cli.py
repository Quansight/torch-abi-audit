"""Command-line entry point for ``torch-abi-audit``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .inspect import inspect_package, inspect_site_packages
from .report import (
    CheckPolicy,
    EnvironmentReport,
    PackageReport,
    collect_violations,
    format_environment_table,
    format_json,
    format_package_table,
    format_violations,
)


def _check_policy(value: str) -> CheckPolicy:
    try:
        return CheckPolicy(value)
    except ValueError:
        choices = ", ".join(CheckPolicy)
        raise argparse.ArgumentTypeError(
            f"invalid policy {value!r} (choose from {choices})"
        ) from None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="torch-abi-audit",
        description="Audit Python extensions for PyTorch (and CPython) Stable ABI compliance.",
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help="Import name or filesystem path of a package or extension module.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--env",
        action="store_true",
        help="Inspect every package in the active interpreter's site-packages.",
    )
    mode.add_argument(
        "--site-packages",
        metavar="PATH",
        help="Inspect every package in the given site-packages directory.",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p.add_argument(
        "--all",
        action="store_true",
        help="In env/site-packages mode, also list packages that don't reference torch.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show offending symbols for unstable / non-compliant modules.",
    )
    p.add_argument(
        "--check",
        type=_check_policy,
        choices=list(CheckPolicy),
        metavar="POLICY",
        help=(
            "CI gate: exit 1 if any inspected package violates POLICY. "
            "'torch' fails on libtorch use without the stable ABI; 'abi3' fails "
            "when a torch-using package isn't CPython abi3-compliant; 'both' "
            "requires both. Operational errors still exit 2."
        ),
    )
    return p


def _run_env_mode(
    site_packages: Path | None,
    json_out: bool,
    show_all: bool,
    verbose: bool,
    check: CheckPolicy | None,
) -> int:
    try:
        report = inspect_site_packages(site_packages)
    except (NotADirectoryError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if json_out:
        print(format_json(report))
    else:
        print(format_environment_table(report, verbose=verbose, show_all=show_all))
    if check:
        violations = collect_violations(report.packages, check)
        if violations:
            print(format_violations(violations, check), file=sys.stderr)
            return 1
    return 0


def _run_target_mode(
    targets: list[str], json_out: bool, verbose: bool, check: CheckPolicy | None
) -> int:
    reports: list[PackageReport] = []
    rc = 0
    for t in targets:
        try:
            reports.append(inspect_package(t))
        except RuntimeError as exc:
            print(f"error inspecting {t}: {exc}", file=sys.stderr)
            rc = 2
    if json_out:
        if len(reports) == 1:
            print(format_json(reports[0]))
        else:
            # Wrap multiple package reports into a synthetic EnvironmentReport-like envelope.
            payload = EnvironmentReport(
                site_packages=Path("."), packages=tuple(reports)
            )
            print(format_json(payload))
    else:
        for r in reports:
            print(format_package_table(r, verbose=verbose))
            print()
    if check:
        violations = collect_violations(reports, check)
        if violations:
            print(format_violations(violations, check), file=sys.stderr)
            # Don't mask an operational error (2) with the policy code (1).
            rc = rc or 1
    return rc


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.env and not args.site_packages and not args.targets:
        print(
            "error: provide at least one TARGET, or --env, or --site-packages PATH",
            file=sys.stderr,
        )
        return 2

    if args.env or args.site_packages:
        sp = Path(args.site_packages).resolve() if args.site_packages else None
        return _run_env_mode(sp, args.json, args.all, args.verbose, args.check)
    return _run_target_mode(args.targets, args.json, args.verbose, args.check)


if __name__ == "__main__":
    sys.exit(main())
