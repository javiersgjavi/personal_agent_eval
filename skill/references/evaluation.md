# Evaluation Reference

Everything about how `personal_agent_eval` scores a run: the six dimensions, what the judge sees, the hybrid aggregation pipeline, and how to read and debug evaluation artifacts.

---

## The six scoring dimensions

The judge scores every run on six dimensions, each on a **0–10 scale**. All dimensions are independent — a high `task` score does not imply a high `efficiency` score.

| Dimension | What it measures |
|---|---|
| `task` | Did the output fulfill the stated goal? Correct content, correct files, correct format. |
| `process` | Was the approach sound? Right tools used, constraints respected, no hallucinated results. |
| `autonomy` | Did the model operate independently? Sensible decisions without over-asking or stalling. |
| `closeness` | Does the response resemble what a skilled human would produce? Tone, framing, completeness. |
| `efficiency` | Was the goal achieved with reasonable resource use? No unnecessary calls, no noise. |
| `spark` | Is there something noteworthy? A useful insight, an elegant shortcut, thoughtful initiative. |

### The `final_score`

`final_score` equals the judge's holistic **overall assessment** (0–10). It is **not** computed from the per-dimension scores — it is the judge's single top-level verdict after considering everything.

The six dimensions exist for diagnostics. They tell you *why* a model scored the way it did, not the other way around.

---

## Hybrid aggregation

For each dimension, the final score can come from three sources configured in the evaluation profile:

| Policy | Calculation |
|---|---|
| `judge_only` (default) | `final = judge_score` |
| `deterministic_only` | `final = deterministic_score` (10.0 if all checks pass, 0.0 if any fail) |
| `weighted` | `final = (judge_score × judge_weight) + (deterministic_score × deterministic_weight)` |

Configure per-dimension policies in `evaluation_profile.yaml → final_aggregation`:

```yaml
final_aggregation:
  default_policy: judge_only        # applies to all dimensions not listed below
  dimensions:
    process:
      policy: weighted
      judge_weight: 0.9
      deterministic_weight: 0.1
    task:
      policy: deterministic_only
```

The shipped profile `judge_gpt54_mini` uses `weighted` for `process` (0.9 judge / 0.1 deterministic) and `judge_only` for all other dimensions.

### How deterministic scores feed in

A deterministic check tagged with `dimensions: [task, process]` contributes to both those dimensions. If the check passes the dimension gets 10.0; if it fails, 0.0. The deterministic dimension score is the average across all checks tagged to that dimension.

Check errors (code exceptions) are excluded and generate a warning — they are not counted as failures.

### Multi-repetition judge aggregation

When `repetitions > 1`, each judge iteration produces its own dimension scores. These are aggregated via `aggregation.method`:

- `median` (default) — median per dimension across successful iterations
- `mean` — mean per dimension
- `majority_vote` — majority across pass/fail threshold

Failed iterations (bad JSON, provider errors) are excluded. If all iterations fail, the evaluation is marked with an error.

---

## What the judge sees

The judge receives a structured "subject view" — not the raw trace. It contains:

- **Original task**: the messages and expectations from the test config
- **Final response**: the last assistant message from the trace
- **Tool activity summary**: tool names used, call count (no raw arguments)
- **Key artifacts**: excerpts of output files (OpenClaw workspace diff, expected artifacts)
- **Deterministic check summary**: pass/fail/error counts and which checks failed
- **Material failures**: anything that blocked completion of a hard expectation

The judge does **not** see: run IDs, container names, full host file paths, raw provider metadata, docker logs, or intermediate trace events.

This design makes judge prompts reproducible and focused on the result — the judge scores the *product*, not the plumbing.

### Inspect what the judge saw

```
outputs/evaluations/suit_<suite_id>/
  evaluation_profile_<fp6>/eval_profile_<eval_id>_<fp6>/<model_id>/<case_id>/
    ├── judge_1.prompt.debug.md       ← system + user prompt concatenated
    └── raw_outputs/
        └── judge_1.prompt.user.json  ← structured JSON of the subject view
```

---

## Reading evaluation artifacts

### Start here: `evaluation_result_summary_1.md`

```
outputs/evaluations/suit_<suite_id>/
  evaluation_profile_<fp6>/eval_profile_<eval_id>_<fp6>/<model_id>/<case_id>/
    └── evaluation_result_summary_1.md
```

Human-readable Markdown containing:
- `final_score` and per-dimension scores
- Judge evidence per dimension (bullet list of observations)
- Deterministic check outcomes (pass/fail with check IDs)
- Warnings

### Drill down: `raw_outputs/final_result_1.json`

The key field is `dimension_resolutions` — it shows exactly how each dimension score was derived:

```json
{
  "final_score": 8.5,
  "judge_overall": { "score": 8.5, "evidence": ["..."] },
  "judge_dimensions": {
    "task": 9.0, "process": 8.0, "autonomy": 8.5,
    "closeness": 8.0, "efficiency": 7.5, "spark": 6.0
  },
  "deterministic_dimensions": { "task": 10.0, "process": 10.0 },
  "final_dimensions": { "task": 9.0, "process": 8.18 },
  "dimension_resolutions": {
    "task": {
      "policy": "judge_only",
      "judge_score": 9.0,
      "deterministic_score": 10.0,
      "final_score": 9.0
    },
    "process": {
      "policy": "weighted",
      "judge_score": 8.0,
      "deterministic_score": 10.0,
      "final_score": 8.18
    }
  },
  "summary": {
    "deterministic_passed_checks": 2,
    "deterministic_failed_checks": 0,
    "judge_successful_iterations": 1,
    "judge_failed_iterations": 0
  }
}
```

### Audit the judge: `judge_1.prompt.debug.md`

The complete judge prompt — system + user — rendered as Markdown. Use this when a score seems wrong or surprising. You can see exactly what context the judge had and whether it received complete, accurate information.

### Runner trace: `run_1.json`

Full event trace at `outputs/runs/suit_<suite_id>/run_profile_<fp6>/<model_id>/<case_id>/run_1.json`. Contains every tool call, tool result, and message, plus token usage and cost. Use this for runner-level debugging: did the model call the right tools? did a tool return an error?

---

## Debugging a score that seems wrong

1. Read `evaluation_result_summary_1.md` — which dimension is low?
2. Check `raw_outputs/final_result_1.json → dimension_resolutions` — is the low score coming from the judge or from a deterministic check?
3. If judge score seems off: open `judge_1.prompt.debug.md` — did the judge receive incomplete or misleading context? Did a hard expectation fail, which caps the score?
4. If a deterministic check failed unexpectedly: look at `raw_outputs/final_result_1.json → summary` for counts, then check the check definitions in `test.yaml` — paths and substrings must match exactly.
5. If the run itself looks wrong: read `run_1.json → trace` — inspect each tool call and result in sequence.

---

## Anchors: calibrating the judge

Add scoring anchors to the evaluation profile to stabilize scores across models and campaigns:

```yaml
anchors:
  enabled: true
  references:
    - anchor_id: perfect_score
      label: "Perfect tool-use chain"
      text: "Used all three tools in order, file contents exact, confirmation clear."
    - anchor_id: partial_score
      label: "Partial completion"
      text: "Ran exec_shell but skipped write_file; confirmed imagined content."
```

When `enabled: true`, anchor texts are injected into the judge system prompt. This is useful when comparing models across many campaigns — anchors give the judge a shared reference frame so scores stay calibrated.

---

## Scoring scale reference

| Score range | Interpretation |
|---|---|
| 9–10 | Excellent: all requirements met, no meaningful flaws |
| 7–8 | Good: mostly correct with minor issues |
| 4–6 | Partial: some requirements met, notable gaps |
| 1–3 | Poor: significant failures, core requirements missed |
| 0 | No attempt, empty output, or completely off-target |

Hard expectation failures typically cap `final_score` at ≤ 4, regardless of partial quality. You can enforce this explicitly via `scoring_instructions` in the rubric.
