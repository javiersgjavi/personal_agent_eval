"""Command line interface for the personal agent evaluation toolkit."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from personal_agent_eval._version import __version__
from personal_agent_eval.reporting import WorkflowReporter
from personal_agent_eval.workflow import WorkflowOrchestrator, WorkflowResult


class CliRuntime(Protocol):
    """Runtime methods that back CLI subcommands."""

    def run(self, *, suite_path: str | Path, run_profile_path: str | Path) -> WorkflowResult:
        """Execute the run workflow."""

    def evaluate(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path,
    ) -> WorkflowResult:
        """Execute the eval workflow."""

    def run_eval(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path,
    ) -> WorkflowResult:
        """Execute the run-eval workflow."""

    def report(
        self,
        *,
        suite_path: str | Path,
        run_profile_path: str | Path,
        evaluation_profile_path: str | Path,
    ) -> WorkflowResult:
        """Render reporting from previously stored artifacts."""


def build_parser() -> argparse.ArgumentParser:
    """Build the root CLI parser and subcommands."""
    parser = argparse.ArgumentParser(
        prog="pae",
        description="Personal Agent Eval command line interface.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level for workflow progress messages.",
    )
    subparsers = parser.add_subparsers(dest="command")
    run_parent = argparse.ArgumentParser(add_help=False)
    run_parent.add_argument("--suite", required=True, help="Path to suite YAML.")
    run_parent.add_argument("--run-profile", required=True, help="Path to run profile YAML.")
    run_parent.add_argument(
        "--output",
        default="text",
        choices=["text", "json"],
        help="Output format for CLI results.",
    )

    run_parser = subparsers.add_parser("run", parents=[run_parent], help="Execute missing runs.")
    run_parser.set_defaults(command="run")

    eval_parent = argparse.ArgumentParser(add_help=False)
    eval_parent.add_argument("--suite", required=True, help="Path to suite YAML.")
    eval_parent.add_argument("--run-profile", required=True, help="Path to run profile YAML.")
    eval_parent.add_argument(
        "--evaluation-profile",
        required=True,
        help="Path to evaluation profile YAML.",
    )
    eval_parent.add_argument(
        "--output",
        default="text",
        choices=["text", "json"],
        help="Output format for CLI results.",
    )

    eval_parser = subparsers.add_parser(
        "eval",
        parents=[eval_parent],
        help="Execute missing runs and missing evaluations.",
    )
    eval_parser.set_defaults(command="eval")

    run_eval_parser = subparsers.add_parser(
        "run-eval",
        parents=[eval_parent],
        help="Execute the full run and evaluation workflow.",
    )
    run_eval_parser.set_defaults(command="run-eval")

    report_parser = subparsers.add_parser(
        "report",
        parents=[eval_parent],
        help="Render reporting from previously stored evaluation artifacts.",
    )
    report_parser.set_defaults(command="report")
    return parser


def main(argv: Sequence[str] | None = None, *, runtime: CliRuntime | None = None) -> int:
    """Run the CLI and emit structured JSON workflow results."""
    parser = build_parser()
    parsed_args = parser.parse_args(list(argv) if argv is not None else None)

    if parsed_args.command is None:
        parser.print_help()
        return 0

    logging.basicConfig(
        level=getattr(logging, parsed_args.log_level),
        format="%(levelname)s %(message)s",
    )

    resolved_runtime = runtime or build_default_runtime(parsed_args.suite)

    if parsed_args.command == "run":
        result = resolved_runtime.run(
            suite_path=parsed_args.suite,
            run_profile_path=parsed_args.run_profile,
        )
    elif parsed_args.command == "eval":
        result = resolved_runtime.evaluate(
            suite_path=parsed_args.suite,
            run_profile_path=parsed_args.run_profile,
            evaluation_profile_path=parsed_args.evaluation_profile,
        )
    elif parsed_args.command == "run-eval":
        result = resolved_runtime.run_eval(
            suite_path=parsed_args.suite,
            run_profile_path=parsed_args.run_profile,
            evaluation_profile_path=parsed_args.evaluation_profile,
        )
    elif parsed_args.command == "report":
        result = resolved_runtime.report(
            suite_path=parsed_args.suite,
            run_profile_path=parsed_args.run_profile,
            evaluation_profile_path=parsed_args.evaluation_profile,
        )
    else:
        parser.error(f"Unsupported command '{parsed_args.command}'.")
        return 2

    reporter = WorkflowReporter()
    if parsed_args.output == "json":
        print(json.dumps(reporter.build_report(result).to_json_dict(), indent=2, sort_keys=True))
    else:
        print(reporter.render_cli(result))
    return 0


def build_default_runtime(suite_path: str | Path) -> WorkflowOrchestrator:
    """Build the default filesystem-backed workflow runtime."""
    suite_root = Path(suite_path).expanduser().resolve().parent.parent
    return WorkflowOrchestrator(storage_root=suite_root)


def run() -> int:
    """Console script entry point."""
    return main()
