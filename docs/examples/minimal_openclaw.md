# Minimal OpenClaw example

This repository ships a small **OpenClaw** example under `configs/` so you can run `pae` with
`runner.type: openclaw` without copying test fixtures. For **installing and operating OpenClaw
itself** (gateway, channels, global config), see the official docs: [OpenClaw documentation](https://docs.openclaw.ai).

The benchmark does **not** use `~/.openclaw/openclaw.json` as the source of truth for evaluation
runs. Instead, for each run it materializes a workspace, writes a **generated** `openclaw.json`,
sets `OPENCLAW_STATE_DIR`, and invokes the `openclaw` CLI **inside the container image** pinned in
the run profile (`docker run`, validate + local agent turn). Your machine needs **Docker** (or a
compatible OCI runtime via `openclaw.docker_cli`) and network access to pull that image. Set
`OPENROUTER_API_KEY` on the host so OpenClaw inside the container can call models via OpenRouter.
Unit tests patch `subprocess.run` instead of running real containers.

## Layout (shipped in this repo)

| Piece | Path |
| --- | --- |
| Reusable agent | `configs/agents/support_agent/` (`agent.yaml` + `workspace/`) |
| Tool case | `configs/cases/openclaw_tool_example/test.yaml` |
| Browser case | `configs/cases/openclaw_browser_example/test.yaml` |
| Suite | `configs/suites/openclaw_examples.yaml` |
| Run profile | `configs/run_profiles/openclaw_examples.yaml` (`openclaw:` block) |

Use an evaluation profile you already have under `configs/evaluation_profiles/` when calling
`pae eval` / `run-eval` / `report`. This repository includes `judge_gpt54_mini.yaml` (resolve it by
filename id: `judge_gpt54_mini`).

The shipped example is intentionally fixed to:

- run model: `minimax/minimax-m2.7`
- judge model: `openai/gpt-5.4-mini`

## Commands (from repository root)

Run only (requires Docker and the pinned OpenClaw image):

```bash
uv run pae run \
  --suite openclaw_examples \
  --run-profile openclaw_examples
```

With evaluation (example profile id in this repo):

```bash
uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

## Further reading

- [Configuration](../configuration.md) — OpenClaw fragments, harness steps, fingerprints
- [Run artifacts](../run_artifacts.md) — `runner_metadata.openclaw` evidence and storage layout
- [Runnable examples](runnable_examples.md) — output tree and example commands
