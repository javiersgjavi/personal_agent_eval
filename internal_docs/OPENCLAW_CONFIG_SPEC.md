# OpenClaw Config Spec

Status: contract for the first OpenClaw implementation (simplified layout)

## Goal

Define a small, stable configuration contract for the `openclaw` runner that:

- stays faithful to real OpenClaw concepts (`openclaw.json`, workspace, state dir)
- avoids inventing a parallel agent model disconnected from OpenClaw
- keeps V2 scope small enough to implement quickly

This spec intentionally favors **simplicity** over maximum flexibility.

## Non-goals for the first implementation

- `harness_version` fields in YAML
- `base_workspace + overlays + files` composition rules
- a full mirror of the OpenClaw JSON schema inside benchmark YAML

Those can return later if we hit real needs.

## OpenClaw concepts we rely on

From [OpenClaw documentation](https://docs.openclaw.ai) (install, gateway, workspace model):

- OpenClaw reads a strict `openclaw.json` (JSON5) config
- the agent workspace is a real directory tree with standard files such as:
  - `AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `TOOLS.md`, optional `memory/`, `skills/`, etc.
- runtime state (sessions, credentials, managed skills) lives under `OPENCLAW_STATE_DIR`,
  separate from the workspace

The benchmark harness must preserve that separation.

## Repository layout for a reusable agent

Each reusable agent is a directory:

```text
configs/agents/<agent_id>/
  agent.yaml
  workspace/
    AGENTS.md
    SOUL.md
    ...
```

Rules:

- `<agent_id>` must match the existing ID pattern used elsewhere in configs
- `agent.yaml` is the typed benchmark-side definition
- `workspace/` is copied wholesale into the ephemeral run workspace
- if standard workspace files are missing, the harness may inject **small placeholders**
  so OpenClaw behaves predictably and judges have stable context

### Why directory-based agents

This matches how OpenClaw thinks about workspaces and keeps agents tangible:

- easy to version in git
- easy to inspect and diff
- avoids complex merge rules early

## Case config (`test.yaml`)

Keep the first OpenClaw cases aligned with the existing canonical case schema:

- `runner.type: openclaw`
- task prompt in `input.messages`
- case-specific files in `input.attachments`
- optional runner hints in `input.context.openclaw.*` when needed
- success criteria in `expectations` and `deterministic_checks`

## `configs/agents/<agent_id>/agent.yaml`

This file defines stable OpenClaw-facing fragments and metadata.

### Required fields

- `schema_version: 1`
- `agent_id` (must match the directory name)
- `title`

### Optional fields

- `description`
- `tags`
- `metadata` (small, JSON-serializable)

### OpenClaw fragments

Use a single `openclaw:` object for benchmark-controlled fragments that should be merged into the
generated `openclaw.json`.

First-pass recommendation: keep this small and explicit.

Allowed keys in V2 initial implementation:

- `identity` (optional)
- `agents_defaults` (optional partial object merged into `agents.defaults`)
- `agent` (optional partial object used to build the single `agents.list[]` entry)
- `model_defaults` (optional):
  - `aliases`
  - other non-primary model tuning

Hard rule:

- do not set a primary model here in a way that bypasses suite/CLI model selection

## `configs/agents/<agent_id>/workspace/`

This directory is the agent workspace template.

The harness copies it into the ephemeral run workspace root.

### Placeholder policy

If a standard file is missing, the harness may create a minimal placeholder file.

Placeholders should be:

- deterministic
- small
- clearly marked as benchmark-generated defaults
- safe to commit publicly (no secrets)

Exact placeholder set can start minimal and expand as we learn what OpenClaw expects in practice.

## Run profile: top-level `openclaw` block

Add a dedicated `openclaw:` object to `run_profile.yaml`.

V2 initial shape should stay minimal:

```yaml
openclaw:
  agent_id: support_agent
  image: ghcr.io/openclaw/openclaw-base:0.1.0
  timeout_seconds: 300
```

Semantics:

- `agent_id` selects `configs/agents/<agent_id>/`
- `image` selects the **OCI/Docker image** in which the harness runs `openclaw` (validate + agent
  turn), via `docker run` (or `openclaw.docker_cli`). See OpenClaw’s Docker docs:
  [docs.openclaw.ai/install/docker](https://docs.openclaw.ai/install/docker).
- `timeout_seconds` is a wall-clock limit for the benchmark run execution

Deferred (explicitly not required in V2 initial YAML):

- default network policy
- extra env injection beyond what the harness needs internally
- persistence toggles (first implementation can always persist the full evidence set)

## OpenRouter (upstream)

The benchmark trajectory assumes **OpenRouter** as the primary LLM path for OpenClaw runs, in line
with the rest of the suite. OpenClaw’s own documentation describes:

- model references such as `openrouter/<provider>/<model>`
- env for API access (e.g. `OPENROUTER_API_KEY`)
- onboarding via CLI flags

See: [OpenRouter — OpenClaw providers](https://docs.openclaw.ai/providers/openrouter).

The harness renderer emits OpenRouter-aligned primary refs (`openrouter/<provider>/<model>`),
`models.default`, `agents.list[0].model`, and `agents.defaults.model.primary`. Secrets stay in the
environment (`OPENROUTER_API_KEY`, etc.), not in committed YAML.

Benchmarking note:
`fallbacks` are not supported for benchmark OpenClaw agents. Otherwise a case nominally run for one
model may complete using another provider/model, which makes the result unsuitable for strict model
evaluation. The loader rejects agent configs that declare fallbacks.

Current compatibility note:

- the benchmark also injects an explicit `models.providers.openrouter` override with the canonical
  `https://openrouter.ai/api/v1` base URL
- reason: some OpenClaw 2026 images were observed persisting or merging the legacy
  `https://openrouter.ai/v1` path into per-agent `models.json`, which correlated with embedded runs
  ending in `payloads=0`, `replayInvalid: true`, and `livenessState: "abandoned"`
- this should be treated as a compatibility shim, not a forever contract; if upstream OpenClaw
  stabilizes provider resolution in newer images, revisit whether the benchmark should keep,
  narrow, or remove this override

## Generated `openclaw.json` composition

The harness generates one `openclaw.json` per run.

### Merge order (conceptual)

1. harness base template (minimal safe defaults for benchmark execution)
2. merge `agent.yaml` fragments under `openclaw:`
3. apply run-profile fields that affect OpenClaw config (`image` affects runtime container, not
   necessarily the JSON — only include JSON fields when they are real OpenClaw config keys)
4. inject the resolved benchmark model as the effective primary model
5. set `agents.defaults.workspace` to the ephemeral workspace path
6. set `OPENCLAW_STATE_DIR` externally / via process environment to the ephemeral state directory

Important:

- the benchmark must not rely on “magic strings” inside the case to construct OpenClaw config
  unless those strings are part of the declared agent fragments

### Validation

Before execution, validate generated config using OpenClaw’s own validation path when available
(for example `openclaw config validate`), or an equivalent strict schema check.

## Harness execution shape

### Shipped path (Docker / OCI)

The harness runs the same logical steps **inside** `run_profile.openclaw.image` (default CLI
`docker`, overridable via `openclaw.docker_cli`):

1. resolve the effective OpenClaw config (including OpenRouter-shaped model refs)
2. materialize the agent workspace into an ephemeral run directory on the host
3. create a separate ephemeral `OPENCLAW_STATE_DIR` on the host
4. write the generated `openclaw.json` under the ephemeral harness root
5. bind-mount that root into the container and invoke `openclaw config validate --json`
6. invoke `openclaw agent --local --json` for one turn

Host environment variables (including provider keys) are forwarded into the container invocation.
Unit tests stub `subprocess.run` instead of starting real containers.

Current task handoff rule:

- flatten the canonical case inputs into one deterministic message payload
- include resolved `input.messages`
- append attachment contents
- append declared `input.context.openclaw` hints when present

Current timeout rule:

- `timeout_seconds` remains a real runtime limit for the harness execution
- it is not part of the semantic reuse identity

## Fingerprints

We want two conceptual layers:

### `agent_fingerprint`

Identity of the reusable agent **after** resolving:

- normalized `agent.yaml` payload
- effective workspace tree contents (paths + file hashes)
- deterministic placeholder injections (if any)

This fingerprint answers:

> did the agent definition change, even if the case stayed the same?

### `run_fingerprint` inputs for OpenClaw

The existing run fingerprint pipeline should incorporate at least:

- runner type (`openclaw`)
- requested benchmark model
- `agent_fingerprint`
- `image`
- case execution inputs that affect the run:
  - resolved `input.messages`
  - resolved attachments (content hashes)
  - relevant `input.context`

Current decision:

- `timeout_seconds` is runtime control metadata, not part of the OpenClaw run compatibility identity

No `harness_version` field is required. If harness logic changes incompatibly later, bump a
**fingerprint payload version** inside the normalized fingerprint JSON (not a user-facing YAML
field).

## Ephemeral run directories

For each OpenClaw run, create:

- `WORKSPACE_RUN_DIR`: ephemeral copy of `configs/agents/<agent_id>/workspace/`
- `STATE_RUN_DIR`: ephemeral OpenClaw state dir (`OPENCLAW_STATE_DIR`)

Never treat these as the same directory.

## Persisted evidence (referenced assets)

Store large assets outside the canonical run artifact JSON and reference them with `OutputArtifactRef`
(or an equivalent reference model).

The benchmark implements this for OpenClaw as `OpenClawRunEvidence` under
`runner_metadata.openclaw` (see `src/personal_agent_eval/artifacts/openclaw_run_evidence.py` and
`docs/run_artifacts.md`).

Minimum categories for V2:

- generated `openclaw.json`
- raw session transcript(s) / JSONL
- OpenClaw logs (paths under `/tmp/openclaw/` or captured stdout/stderr)
- workspace snapshot archive
- workspace diff artifact

Current storage rule:

- the runner may first emit temporary local `file://` refs
- filesystem storage relocates those refs into stable run-scoped artifact directories
  (`run_N.artifacts/`) when persisting the canonical `RunArtifact`

## Fixtures

Shipped examples live under:

- `configs/agents/support_agent/` (repository root)
- `configs/cases/openclaw_smoke/` with suite `openclaw_smoke_suite` and run profile `openclaw_smoke`

Keep them small and deterministic.
