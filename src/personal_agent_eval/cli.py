"""Command line bootstrap for the personal agent evaluation toolkit."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from personal_agent_eval._version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the root CLI parser for future subcommands."""
    parser = argparse.ArgumentParser(
        prog="pae",
        description="Personal Agent Eval command line interface.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and reserve the surface for future commands."""
    parser = build_parser()
    parser.parse_args(list(argv) if argv is not None else None)
    parser.print_help()
    return 0


def run() -> int:
    """Console script entry point."""
    return main()
