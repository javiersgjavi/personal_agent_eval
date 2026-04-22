# Getting Started

This page shows the minimal mental model for running V1 of `personal_agent_eval`.

## Core Files

V1 uses four YAML file types:

1. `configs/cases/<case_id>/test.yaml`
2. `configs/suites/<suite_id>.yaml`
3. `configs/run_profiles/<profile_id>.yaml`
4. `configs/evaluation_profiles/<profile_id>.yaml`

They answer four different questions:

- `test.yaml`: what is the case
- `suite.yaml`: which cases and models should be grouped together
- `run_profile.yaml`: how should execution run
- `evaluation_profile.yaml`: how should results be judged and aggregated

## Minimal Workflow

The intended V1 flow is:

1. define one or more cases
2. define a suite that selects those cases
3. define a run profile for execution behavior
4. define an evaluation profile for judges and hybrid aggregation
5. execute the workflow through `pae`

V1 now exposes these orchestration commands:

- `pae run`
- `pae eval`
- `pae run-eval`
- `pae report`

**OpenClaw:** cases with `runner.type: openclaw` use the same commands. Choose a run profile
that defines `openclaw` (`agent_id`, `image`, `timeout_seconds`, optional `docker_cli`) and keep the
reusable agent under `configs/agents/<agent_id>/` (`agent.yaml` plus `workspace/`). The workflow
resolves the agent into run fingerprints, runs the OpenClaw harness **only via Docker** using that
pinned image (`openclaw` CLI inside the container), and persists artifacts for reuse like
`llm_probe` runs. The generated `openclaw.json` uses **OpenRouter-style** model refs
(`openrouter/…` and `agents.defaults.model.primary`); set `OPENROUTER_API_KEY` (and any other
required provider env) on the host before running.

For **upstream OpenClaw** (install, gateway, channels, day-to-day config), see the official
documentation: [docs.openclaw.ai](https://docs.openclaw.ai). This framework generates a **per-run**
`openclaw.json` under a temporary directory; that is separate from a developer’s optional global
config at `~/.openclaw/openclaw.json`. A minimal runnable layout lives under `configs/`; see
[Minimal OpenClaw example](examples/minimal_openclaw.md).

When working inside this repository, prefer running the CLI via `uv`:

```bash
uv run pae --help
```

If you installed `personal_agent_eval` into an active virtualenv (or globally), you can also run:

```bash
pae --help
```

The CLI accepts either explicit YAML paths or config ids for:

- `--suite`
- `--run-profile`
- `--evaluation-profile`

When an id is provided, the CLI resolves it automatically under the conventional workspace
directories:

- `configs/suites/<suite_id>.yaml`
- `configs/run_profiles/<run_profile_id>.yaml`
- `configs/evaluation_profiles/<evaluation_profile_id>.yaml`

Minimal examples:

```bash
uv run pae run \
  --suite configs/suites/example_suite.yaml \
  --run-profile configs/run_profiles/default.yaml

uv run pae eval \
  --suite configs/suites/example_suite.yaml \
  --run-profile configs/run_profiles/default.yaml \
  --evaluation-profile configs/evaluation_profiles/default.yaml

uv run pae run-eval \
  --suite configs/suites/example_suite.yaml \
  --run-profile configs/run_profiles/default.yaml \
  --evaluation-profile configs/evaluation_profiles/default.yaml

uv run pae report \
  --suite configs/suites/example_suite.yaml \
  --run-profile configs/run_profiles/default.yaml \
  --evaluation-profile configs/evaluation_profiles/default.yaml
```

Equivalent id-based commands:

```bash
uv run pae run \
  --suite example_suite \
  --run-profile default

uv run pae eval \
  --suite example_suite \
  --run-profile default \
  --evaluation-profile default

uv run pae run-eval \
  --suite example_suite \
  --run-profile default \
  --evaluation-profile default

uv run pae report \
  --suite example_suite \
  --run-profile default \
  --evaluation-profile default
```

The CLI now renders human-readable reporting by default and can also emit structured JSON
with `--output json`.

## Runnable Example Campaigns

This repository ships two small campaigns that work as documentation and as real commands:

- `llm_probe_examples`
- `openclaw_examples`

They both use:

- run model: `minimax/minimax-m2.7`
- judge model: `openai/gpt-5.4-mini`

Commands:

```bash
uv run pae run-eval \
  --suite llm_probe_examples \
  --run-profile llm_probe_examples \
  --evaluation-profile judge_gpt54_mini

uv run pae run-eval \
  --suite openclaw_examples \
  --run-profile openclaw_examples \
  --evaluation-profile judge_gpt54_mini
```

See [Runnable examples](examples/runnable_examples.md) for the exact case files and the generated
output layout.

Example:

```bash
uv run pae run-eval \
  --suite configs/suites/example_suite.yaml \
  --run-profile configs/run_profiles/default.yaml \
  --evaluation-profile configs/evaluation_profiles/default.yaml \
  --output json
```

For **`eval`**, **`run-eval`**, and **`report`**, the CLI also **writes a score-vs-cost chart PNG**
by default under `outputs/charts/<evaluation_profile_id>/score_cost.png` (requires the optional
`[charts]` extra). Use **`--no-chart`** to skip it, or **`--chart /path/to/file.png`** for a custom
destination. Chart status lines go to **stderr** so JSON on stdout stays parseable.

The reporting layer is a pure consumer of structured workflow results and can render:

- per-model per-case tables (including run vs evaluation cost split and run latency)
- per-model summaries (including average latency and cost split)
- JSON report payloads (including workflow-level cost totals)
- basic ASCII charts
- optional matplotlib bubble chart (score vs cost, bubble size ~ latency)

See [Reporting](reporting.md) for column names and structured fields.

Execution artifacts are stored under suite-scoped campaign directories. For example, runs now
land under paths like:

```text
outputs/runs/suit_<suite_id>/run_profile_<run_profile_fingerprint_short6>/<model_id>/<case_id>/run_1.json
```

If `execution_policy.run_repetitions` is greater than `1`, the workflow stores `run_1.json`,
`run_2.json`, and so on in that same case directory and then aggregates those repetitions back
into one case-level workflow result in the CLI/reporting layer.

## Minimal Repository Shape

```text
configs/
  cases/
    example_case/
      test.yaml
  suites/
    example_suite.yaml
  run_profiles/
    default.yaml
  evaluation_profiles/
    default.yaml
```

## Minimal Output Mental Model

One run produces a canonical run artifact:

```json
{
  "run_id": "run_001",
  "case_id": "example_case",
  "runner_type": "llm_probe",
  "status": "success"
}
```

Deterministic evaluation produces structured check results:

```json
{
  "case_id": "example_case",
  "run_id": "run_001",
  "summary": {
    "passed_checks": 2,
    "failed_checks": 0
  }
}
```

Judge orchestration produces per-iteration and aggregated judge outputs:

```json
{
  "judge_name": "primary_judge",
  "configured_repetitions": 3,
  "successful_iterations": 3,
  "aggregation_method": "median"
}
```

Hybrid aggregation produces the final evaluation result:

```json
{
  "case_id": "example_case",
  "run_id": "run_001",
  "deterministic_dimensions": {
    "task": 10.0,
    "process": 10.0
  },
  "judge_dimensions": {
    "task": 8.0,
    "process": 7.0,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 6.0,
    "spark": 6.0
  },
  "final_dimensions": {
    "task": 8.6,
    "process": 8.2,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 6.0,
    "spark": 6.0
  },
  "final_score": 7.13
}
```

CLI orchestration already produces per-`model_id` and per-`case_id` workflow results, and the
CLI can present them either as terminal reporting or as structured JSON.

## Important V1 Rules

- `llm_probe` is the implemented runtime target
- automated tests should stay mocked wherever possible
- OpenRouter may be used for tiny, deliberate smoke tests only
- judge output and deterministic output stay separate from the final hybrid result
- the judge is the default prevailing source unless aggregation config says otherwise

## Optional Real OpenRouter Smoke Test

The repository includes one real OpenRouter smoke test for the full `run-eval` path. It
covers:

- real `llm_probe` execution against OpenRouter
- real judge execution against OpenRouter
- final hybrid aggregation and persisted artifacts

It is gated so normal local runs and CI do not spend tokens by accident.

Required environment variables:

- `OPENROUTER_API_KEY`: real OpenRouter API key
- `PERSONAL_AGENT_EVAL_RUN_OPENROUTER_E2E=1`: explicit opt-in switch

Optional environment variable:

- `PERSONAL_AGENT_EVAL_OPENROUTER_E2E_RUN_MODEL`: override the run model
- `PERSONAL_AGENT_EVAL_OPENROUTER_E2E_JUDGE_MODEL`: override the judge model

If those optional overrides are omitted, both default to `openai/gpt-4o-mini`.

Example:

```bash
PERSONAL_AGENT_EVAL_RUN_OPENROUTER_E2E=1 \
OPENROUTER_API_KEY=... \
uv run pytest tests/test_openrouter_e2e.py -m openrouter_e2e
```

## Next Reading

- [Config Model](config_model.md) — how the four YAML types relate and where artifacts land
- [Configuration](configuration.md)
- [Judge results](judge_results.md)
- [Hybrid evaluation](hybrid_evaluation.md)
- [Reporting](reporting.md)
- [Minimal llm_probe example](examples/minimal_llm_probe.md)
