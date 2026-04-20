# Minimal OpenClaw example

This repository ships a small **OpenClaw** example under `configs/` so you can run `pae` with
`runner.type: openclaw` without copying test fixtures. For **installing and operating OpenClaw
itself** (gateway, channels, global config), see the official docs: [OpenClaw documentation](https://docs.openclaw.ai).

The benchmark does **not** use `~/.openclaw/openclaw.json` as the source of truth for evaluation
runs. Instead, for each run it materializes a workspace, writes a **generated** `openclaw.json`,
sets `OPENCLAW_STATE_DIR`, and invokes the `openclaw` CLI (validate + local agent turn). Your
machine still needs the `openclaw` executable on `PATH` if you execute real harness runs (tests
often inject a fake executor).

## Layout (shipped in this repo)

| Piece | Path |
| --- | --- |
| Reusable agent | `configs/agents/support_agent/` (`agent.yaml` + `workspace/`) |
| Case | `configs/cases/openclaw_smoke/test.yaml` |
| Suite | `configs/suites/openclaw_smoke_suite.yaml` |
| Run profile | `configs/run_profiles/openclaw_smoke.yaml` (`openclaw:` block) |

Use an evaluation profile you already have under `configs/evaluation_profiles/` when calling
`pae eval` / `run-eval` / `report`. This repository includes `judge_gpt54_mini.yaml` (resolve it by
filename id: `judge_gpt54_mini`).

## Commands (from repository root)

Run only (requires working OpenClaw CLI or tests with injected executor):

```bash
uv run pae run \
  --suite openclaw_smoke_suite \
  --run-profile openclaw_smoke
```

With evaluation (example profile id in this repo):

```bash
uv run pae run-eval \
  --suite openclaw_smoke_suite \
  --run-profile openclaw_smoke \
  --evaluation-profile judge_gpt54_mini
```

## Further reading

- [Configuration](../configuration.md) — OpenClaw fragments, harness steps, fingerprints
- [Run artifacts](../run_artifacts.md) — `runner_metadata.openclaw` evidence and storage layout
