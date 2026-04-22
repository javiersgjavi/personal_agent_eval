# Judge Results

The judge is an LLM that reads a compact, structured view of the run and produces a scored assessment across six dimensions. It runs after the deterministic layer, and its output defines the final score.

---

## What the judge sees

The judge receives two messages: a **system prompt** (the evaluation contract) and a **user prompt** (the structured subject view).

The subject view is a compact JSON document with three sections:

### 1. Evaluation target
What the subject was asked to do:
- task messages from the test case
- hard and soft expectations
- declared scoring dimensions

### 2. Subject response
What the subject produced:
- final output (if present)
- assistant messages
- tool activity summary (tool names used, call count)

### 3. Execution evidence
Signals relevant for process scoring:
- deterministic check summary (passed / failed / error counts)
- filtered trace events (tool calls and results)
- key generated artifacts (for OpenClaw runs, excerpts of workspace files)
- material failures that blocked task completion

The judge does **not** see infrastructure details: run IDs, container image names, filesystem paths, provider metadata, raw Docker logs, or config generation steps. The prompt is designed to surface only what matters for evaluation.

---

## What the judge is asked to produce

The judge returns a structured JSON response with:

```json
{
  "dimensions": {
    "task":       { "evidence": ["..."], "score": 8.5 },
    "process":    { "evidence": ["..."], "score": 7.0 },
    "autonomy":   { "evidence": ["..."], "score": 7.5 },
    "closeness":  { "evidence": ["..."], "score": 8.0 },
    "efficiency": { "evidence": ["..."], "score": 6.5 },
    "spark":      { "evidence": ["..."], "score": 5.0 }
  },
  "overall": {
    "evidence": ["Used all required tools", "File content matches the marker"],
    "score": 7.8
  }
}
```

Each dimension score is on a 0–10 scale. The `evidence` items are concise factual observations that support the score — not vague qualitative statements.

---

## The six dimensions

| Dimension | What the judge is measuring |
|---|---|
| `task` | Did the output fulfill the stated goal? Correct content, correct files, correct format. |
| `process` | Did the agent follow a sound approach? Right tools, respected constraints, no hallucinated steps. |
| `autonomy` | Did the agent operate independently? Sound decisions without over-asking or needing hand-holding. |
| `closeness` | Did the output match what a thoughtful human response would look like? Tone, framing, completeness. |
| `efficiency` | Did the agent achieve the goal without waste? No unnecessary tool calls, no verbose noise. |
| `spark` | Did the response show something noteworthy? Useful insight, elegant shortcut, thoughtful initiative. |

The overall score (`overall.score`) is the judge's holistic verdict after reviewing all evidence. It is not a weighted average of the six dimensions — it is an independent holistic assessment.

---

## Judge repetitions

The evaluation profile can run the judge multiple times and aggregate across iterations:

```yaml
judge_runs:
  - judge_run_id: gpt54_single
    judge_id: gpt54_judge
    repetitions: 3              # call the judge 3 times
aggregation:
  method: median                # take the median across successful iterations
```

Failed or excluded iterations are visible in the raw output but do not contribute to the aggregated score. The aggregated result records:

- `configured_repetitions` — how many were requested
- `successful_iterations` — how many produced valid output
- `aggregation_method` — `median` or `mean`
- the median/mean score per dimension and overall

---

## Output files

After evaluation, three files are written per `(model, case, repetition)`:

| File | Contents |
|---|---|
| `evaluation_result_summary_1.md` | Human-readable Markdown summary: score, dimensions, evidence, deterministic context |
| `judge_1.prompt.debug.md` | The exact prompt shown to the judge (system + user, rendered as readable text) |
| `raw_outputs/judge_1.json` | Raw aggregated judge result (structured JSON) |
| `raw_outputs/judge_1.prompt.user.json` | Structured subject view payload sent as the user message |
| `raw_outputs/final_result_1.json` | Final evaluation result with judge output and deterministic summaries |

**Start with `evaluation_result_summary_1.md`** to understand the verdict. Open `judge_1.prompt.debug.md` to audit what the judge saw. Use `raw_outputs/final_result_1.json` for downstream processing.

---

## Reading `evaluation_result_summary_1.md`

Example (abbreviated):

```markdown
# Evaluation Result

**Case:** llm_probe_tool_example
**Model:** minimax/minimax-m2.7
**Final score:** 8.50 / 10

## Overall assessment
- Used exec_shell, write_file, and read_file correctly
- File content matches the required marker
- Confirmation was brief and accurate

## Dimension scores

| Dimension   | Deterministic | Judge | Final |
|-------------|---------------|-------|-------|
| task        | 10.0          | 8.5   | 8.5   |
| process     | 10.0          | 9.0   | 9.0   |
| autonomy    | n/a           | 8.0   | 8.0   |
| closeness   | n/a           | 8.5   | 8.5   |
| efficiency  | n/a           | 7.5   | 7.5   |
| spark       | n/a           | 6.0   | 6.0   |

## Deterministic checks

| Check                        | Result |
|------------------------------|--------|
| final-response-present       | PASS   |
| llm-probe-tool-example-file  | PASS   |
```

---

## Warnings

If a judge iteration fails (provider error, invalid output, timeout), the result records a warning and that iteration is excluded from aggregation. Warnings surface in the CLI table as a count in the `WARNINGS` column.

Example warning: `Judge iteration 2 failed and was excluded.`

If all iterations fail, the evaluation result still exists but has `evaluation_status: failed` in the workflow result.

---

## Configuring the judge

Judges are defined in the evaluation profile:

```yaml
judges:
  - judge_id: my_judge
    type: llm_probe          # uses the llm_probe runner path for judge calls
    model: openai/gpt-5.4-mini
```

The `judge_system_prompt_path` field points to a Markdown file that contains the scoring contract. The framework includes a default system prompt that encodes the six dimensions and the expected JSON output schema. You can override it per evaluation profile.

→ [Hybrid evaluation](hybrid_evaluation.md) — how judge scores and deterministic signals are stored together
