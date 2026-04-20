"""Stub OpenClaw harness ``docker run`` by replacing ``subprocess.run``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _harness_host_root_from_docker_argv(argv: list[str]) -> Path | None:
    for idx, part in enumerate(argv):
        if part != "-v" or idx + 1 >= len(argv):
            continue
        spec = argv[idx + 1]
        host_part = spec.split(":", 2)[0]
        if host_part:
            return Path(host_part)
    return None


def patch_openclaw_docker_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    validation_ok: bool = True,
    run_stdout: str = '{"content": "Generated report.md"}',
    write_report_md: bool = True,
) -> None:
    """Patch ``subprocess.run`` in the OpenClaw runner module."""

    target = "personal_agent_eval.domains.openclaw.runner.subprocess.run"

    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        _ = kwargs
        if "validate" in argv:
            if validation_ok:
                return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="invalid config\n")
        host_root = _harness_host_root_from_docker_argv(argv)
        if write_report_md and host_root is not None and "agent" in argv:
            report = host_root / "workspace" / "report.md"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("# Report\n\nstub\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=run_stdout, stderr="mock log output\n")

    monkeypatch.setattr(target, fake_run)
