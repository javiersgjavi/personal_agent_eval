from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from personal_agent_eval.cli import main


def test_cli_main_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Personal Agent Eval command line interface." in captured.out
    assert "usage: pae" in captured.out


def test_cli_module_help_runs_from_src_layout() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")

    result = subprocess.run(
        [sys.executable, "-m", "personal_agent_eval", "--help"],
        capture_output=True,
        check=False,
        cwd=root,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert "usage: pae" in result.stdout
