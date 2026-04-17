"""Command line interface for the personal agent evaluation toolkit."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ResolvedConfigReference:
    """CLI argument plus canonical resolved path."""

    cli_value: str
    resolved_path: Path


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
    run_parent.add_argument(
        "--suite",
        required=True,
        help="Suite path or suite_id discovered under configs/suites/.",
    )
    run_parent.add_argument(
        "--run-profile",
        required=True,
        help="Run profile path or run_profile_id discovered under configs/run_profiles/.",
    )
    run_parent.add_argument(
        "--output",
        default="text",
        choices=["text", "json"],
        help="Output format for CLI results.",
    )

    run_parser = subparsers.add_parser("run", parents=[run_parent], help="Execute missing runs.")
    run_parser.set_defaults(command="run")

    eval_parent = argparse.ArgumentParser(add_help=False)
    eval_parent.add_argument(
        "--suite",
        required=True,
        help="Suite path or suite_id discovered under configs/suites/.",
    )
    eval_parent.add_argument(
        "--run-profile",
        required=True,
        help="Run profile path or run_profile_id discovered under configs/run_profiles/.",
    )
    eval_parent.add_argument(
        "--evaluation-profile",
        required=True,
        help="Evaluation profile path or evaluation_profile_id discovered under configs/evaluation_profiles/.",
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

    try:
        suite_reference = resolve_config_reference(
            parsed_args.suite,
            config_kind="suite",
            search_root=Path.cwd(),
            conventional_directory="configs/suites",
        )
        workspace_root = workspace_root_from_config_path(suite_reference.resolved_path)
        run_profile_reference = resolve_config_reference(
            parsed_args.run_profile,
            config_kind="run profile",
            search_root=workspace_root,
            conventional_directory="configs/run_profiles",
        )
        evaluation_profile_reference = None
        if hasattr(parsed_args, "evaluation_profile"):
            evaluation_profile_reference = resolve_config_reference(
                parsed_args.evaluation_profile,
                config_kind="evaluation profile",
                search_root=workspace_root,
                conventional_directory="configs/evaluation_profiles",
            )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    resolved_runtime = runtime or build_default_runtime(suite_reference.resolved_path)

    if parsed_args.command == "run":
        result = resolved_runtime.run(
            suite_path=suite_reference.cli_value,
            run_profile_path=run_profile_reference.cli_value,
        )
    elif parsed_args.command == "eval":
        assert evaluation_profile_reference is not None
        result = resolved_runtime.evaluate(
            suite_path=suite_reference.cli_value,
            run_profile_path=run_profile_reference.cli_value,
            evaluation_profile_path=evaluation_profile_reference.cli_value,
        )
    elif parsed_args.command == "run-eval":
        assert evaluation_profile_reference is not None
        result = resolved_runtime.run_eval(
            suite_path=suite_reference.cli_value,
            run_profile_path=run_profile_reference.cli_value,
            evaluation_profile_path=evaluation_profile_reference.cli_value,
        )
    elif parsed_args.command == "report":
        assert evaluation_profile_reference is not None
        result = resolved_runtime.report(
            suite_path=suite_reference.cli_value,
            run_profile_path=run_profile_reference.cli_value,
            evaluation_profile_path=evaluation_profile_reference.cli_value,
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
    suite_root = workspace_root_from_config_path(Path(suite_path).expanduser().resolve())
    return WorkflowOrchestrator(storage_root=suite_root)


def workspace_root_from_config_path(config_path: Path) -> Path:
    """Return the workspace root for a config path under configs/."""
    resolved_path = config_path.expanduser().resolve()
    if resolved_path.parent.parent.name == "configs":
        return resolved_path.parent.parent.parent
    return resolved_path.parent.parent


def resolve_config_reference(
    value: str | Path,
    *,
    config_kind: str,
    search_root: Path,
    conventional_directory: str,
) -> ResolvedConfigReference:
    """Resolve either an explicit YAML path or an id under a conventional directory."""
    raw_value = str(value)
    candidate_path = Path(raw_value).expanduser()

    if _looks_like_explicit_path(raw_value):
        return ResolvedConfigReference(
            cli_value=raw_value,
            resolved_path=candidate_path.resolve(),
        )

    matches = [
        (search_root / conventional_directory / f"{raw_value}{suffix}").resolve()
        for suffix in (".yaml", ".yml")
        if (search_root / conventional_directory / f"{raw_value}{suffix}").exists()
    ]
    if len(matches) == 1:
        return ResolvedConfigReference(cli_value=str(matches[0]), resolved_path=matches[0])
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous {config_kind} id '{raw_value}': found multiple matches under "
            f"'{search_root / conventional_directory}'. Use an explicit path."
        )
    raise ValueError(
        f"Could not resolve {config_kind} '{raw_value}' under "
        f"'{search_root / conventional_directory}'. Pass an explicit path or create "
        f"'{conventional_directory}/{raw_value}.yaml'."
    )


def _looks_like_explicit_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or Path(value).suffix.lower() in {".yaml", ".yml"}
    )


def run() -> int:
    """Console script entry point."""
    return main()
