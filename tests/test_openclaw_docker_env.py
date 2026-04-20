"""Tests for OpenClaw Docker environment forwarding."""

from __future__ import annotations

from pathlib import Path

import pytest

from personal_agent_eval.domains.openclaw import runner


def test_host_environment_for_openclaw_container_forwards_openrouter_and_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(runner._OPENCLAW_DOCKER_FULL_ENV_FLAG, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8888")
    monkeypatch.setenv("NOISE_FROM_HOST", "ignore-me")
    got = runner._host_environment_for_openclaw_container()
    assert got["OPENROUTER_API_KEY"] == "sk-or-test"
    assert got["OPENROUTER_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert got["HTTPS_PROXY"] == "http://proxy:8888"
    assert "NOISE_FROM_HOST" not in got


def test_host_environment_for_openclaw_container_normalizes_legacy_openrouter_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(runner._OPENCLAW_DOCKER_FULL_ENV_FLAG, raising=False)
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/v1")

    got = runner._host_environment_for_openclaw_container()

    assert got["OPENROUTER_BASE_URL"] == "https://openrouter.ai/api/v1"


def test_host_environment_full_flag_includes_arbitrary_host_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner._OPENCLAW_DOCKER_FULL_ENV_FLAG, "1")
    monkeypatch.setenv("CUSTOM_FOR_CONTAINER", "yes")
    got = runner._host_environment_for_openclaw_container()
    assert got["CUSTOM_FOR_CONTAINER"] == "yes"


def test_docker_openclaw_argv_uses_env_file_and_remaps_paths(tmp_path: Path) -> None:
    cfg = tmp_path / "openclaw.json"
    cfg.write_text("{}", encoding="utf-8")
    st = tmp_path / "state"
    st.mkdir()
    argv = runner._docker_openclaw_argv(
        docker_cli="docker",
        image="openclaw:test",
        workdir=runner.OPENCLAW_DOCKER_WORKDIR,
        config_path=cfg,
        env={
            "OPENROUTER_API_KEY": "sk-x",
            "OPENCLAW_CONFIG_PATH": str(cfg),
            "OPENCLAW_STATE_DIR": str(st),
        },
        inner_command=["openclaw", "config", "validate", "--json"],
    )
    assert "--env-file" in argv
    ef_path = Path(argv[argv.index("--env-file") + 1])
    assert ef_path.is_file()
    body = ef_path.read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-x\n" in body
    assert f"OPENCLAW_CONFIG_PATH={runner.OPENCLAW_DOCKER_WORKDIR}/openclaw.json\n" in body
    assert f"OPENCLAW_STATE_DIR={runner.OPENCLAW_DOCKER_WORKDIR}/state\n" in body


def test_build_openclaw_environment_sets_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(runner._OPENCLAW_DOCKER_FULL_ENV_FLAG, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "present")
    cfg = tmp_path / "openclaw.json"
    cfg.write_text("{}", encoding="utf-8")
    st = tmp_path / "st"
    merged = runner._build_openclaw_environment(config_path=cfg, state_dir=st)
    assert merged["OPENCLAW_CONFIG_PATH"] == str(cfg)
    assert merged["OPENCLAW_STATE_DIR"] == str(st)
    assert merged["OPENROUTER_API_KEY"] == "present"
    assert st.is_dir()
