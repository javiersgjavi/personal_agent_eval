# Fingerprints & Reuse

`personal_agent_eval` uses SHA-256 fingerprints to identify runs and evaluations. This is the mechanism that makes campaigns **incremental** and **reproducible**: no combination is re-executed unless its inputs have changed.

---

## What is a fingerprint?

A fingerprint is a deterministic SHA-256 hash computed from a normalized JSON payload of all the inputs that matter for one execution. If the inputs are the same, the hash is the same. If anything relevant changes, the hash changes.

There are three kinds of fingerprints:

| Kind | What it identifies |
|---|---|
| **Run fingerprint** | One `(model, case, run_profile, repetition)` combination |
| **Evaluation fingerprint** | One `(evaluation_profile)` configuration |
| **OpenClaw agent fingerprint** | One `(agent_config, workspace content)` bundle |

---

## What goes into a run fingerprint?

The run fingerprint payload covers everything that determines what a model will receive and how it will execute:

| Field | Source |
|---|---|
| `runner_type` | `test.yaml → runner.type` |
| `requested_model` | suite model entry |
| `runner_config` | resolved execution parameters (temperature, max_tokens, timeout, retries, etc.) |
| `input_messages` | `test.yaml → input.messages` (content + role, normalized) |
| `input_context` | `test.yaml → input.context` (tool list, openclaw context, etc.) |
| `attachments` | file SHA-256 + byte size (content-addressed, not path-addressed) |
| `case_metadata` | `test.yaml → metadata` |
| `repetition_index` | the repetition number (0-based) |
| `openclaw_agent_fingerprint` | the agent+workspace fingerprint (OpenClaw only) |

The hash is a SHA-256 of the canonical JSON serialization of these fields. Floating-point values in the fingerprint input are **not rounded** to keep the hash stable.

---

## What goes into an evaluation fingerprint?

The evaluation fingerprint covers everything that determines how runs are judged:

| Field | Source |
|---|---|
| `judges` | judge model, type, and all settings |
| `judge_runs` | repetitions per judge |
| `judge_aggregation` | aggregation method (e.g. `median`) |
| `final_aggregation` | dimension policies and weights |
| `anchors` | scoring anchors if enabled |
| `security_policy` | redaction settings, allowed hooks |
| `judge_system_prompt` | the fingerprint of the system prompt file |

---

## What changes the fingerprint?

### Run fingerprint changes when you change:

- `temperature`, `max_tokens`, `timeout_seconds`, `max_turns`, `retries`
- model ID or gateway
- case input messages or context
- attachment file contents
- case metadata
- the workspace template for OpenClaw agents

### Run fingerprint does NOT change when you:

- add a new case to the suite (the new case gets its own fingerprint; existing cases are unaffected)
- add a new model to the suite
- change the suite title or metadata
- increase `run_repetitions` (each repetition has its own fingerprint; only new ones are computed)

### Evaluation fingerprint changes when you change:

- the judge model
- the number of judge repetitions
- aggregation settings
- dimension policies or weights
- the judge system prompt file

---

## Storage paths and `fp6`

Artifacts are stored under paths that include the first 6 characters of the fingerprint (`fp6`):

```text
outputs/runs/suit_{suite_id}/run_profile_{fp6}/
outputs/evaluations/suit_{suite_id}/evaluation_profile_{fp6}/eval_profile_{eval_id}_{fp6}/
```

When you change the run profile in a way that changes the fingerprint, a **new directory** is created. The old directory — and all its results — is preserved. You can always go back and compare.

---

## The reuse decision

Before executing any `(model, case, repetition)` combination, the workflow computes the expected fingerprint and checks whether a matching artifact exists in storage. The outcome is one of three actions:

| Action | Meaning |
|---|---|
| `reuse_all` | Run and evaluation artifacts exist and match; nothing is executed |
| `reuse_run_only` | Run artifact matches; evaluation is missing or changed → only evaluate |
| `execute_new_run` | Run artifact is missing or changed → execute run and then evaluate |

The `RUN` and `EVAL` columns in the CLI output (`reuse` / `exec`) reflect this decision for each row.

---

## The fingerprint input file

Every stored run artifact has a companion `run_1.fingerprint_input.json` file. This file records the exact normalized payload that was hashed to produce the fingerprint. It is useful for:

- understanding exactly what the framework considered when deciding to reuse a result
- debugging unexpected re-executions (compare the stored payload with the current config)
- audit trails: the fingerprint input is what you'd need to reproduce the exact same run

Example:

```json
{
  "fingerprint_version": 1,
  "hash_algorithm": "sha256",
  "kind": "run",
  "fingerprint": "a3f8...",
  "payload": {
    "runner_type": "llm_probe",
    "requested_model": "minimax/minimax-m2.7",
    "runner_config": {
      "temperature": 0,
      "max_tokens": 768,
      "timeout_seconds": 90
    },
    "input_messages": [
      {"role": "user", "content": "Use real tools to..."}
    ],
    "input_context": {
      "llm_probe": {"tools": ["exec_shell", "write_file", "read_file"]}
    },
    "attachments": [],
    "case_metadata": {}
  }
}
```

---

## How to force a re-run

The framework never re-executes unless it has to. To trigger a re-run:

**Delete the artifact:**

```bash
# force one specific case+model combination
rm outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.json
rm outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.fingerprint_input.json
```

**Change the run profile:**

Modify any execution parameter (e.g. bump `temperature` from 0 to 0.1). The fingerprint changes, a new directory is created, and all cases re-run. The old directory is untouched.

**Use a narrow suite:**

Create a suite with only the cases you want to re-run. They land in a different `suit_<id>` directory from the original campaign.

→ [CLI reference — re-running specific cases](cli.md#re-running-specific-cases)

---

## OpenClaw agent fingerprint

For OpenClaw runs, the agent fingerprint covers:

- `agent_id`
- the full `agent.yaml` content (identity, model defaults, sandbox settings)
- the SHA-256 and size of every file in `workspace/`

This means: if you change `SOUL.md` or `AGENTS.md` in the workspace template, the agent fingerprint changes, and all OpenClaw runs that use that agent get a new run fingerprint and will re-execute.

The agent fingerprint is embedded into the run fingerprint, so a changed workspace is enough to invalidate all stored results.

---

## Fingerprint stability guarantees

- Fingerprints are **stable across Python versions and platforms** because they hash a canonical JSON serialization, not a Python object.
- **Floating-point values are not rounded** in fingerprint payloads (only in reporting output).
- The `fingerprint_version: 1` field in the stored payload allows future migrations if the hashing scheme ever changes.
