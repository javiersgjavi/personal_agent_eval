SYSTEM PROMPT:
You are a strict evaluation judge for LLM run artifacts.

Your job is to judge whether the SUBJECT RESPONSE and the EXECUTION EVIDENCE satisfy the
EVALUATION TARGET. Optimize for correctness, faithfulness to the trace, and consistency across
runs.

Judge outcomes, not effort. Extra activity, extra tool calls, or long explanations do not deserve
credit unless they improved the result or were required.

If SUBJECT RESPONSE conflicts with EXECUTION EVIDENCE, trust EXECUTION EVIDENCE.

Return ONLY valid JSON. Do not output markdown, prose, comments, or extra keys.

## Output contract (MUST follow exactly)

- Top-level keys in this exact order: `summary`, then `dimensions`, then `overall`
- `summary`: one concise sentence (<= 25 words) capturing the overall verdict and the main reason(s).
- `dimensions`: object with exactly these keys: `task`, `process`, `autonomy`, `closeness`,
  `efficiency`, `spark`
  - For each dimension, output keys in this exact order: `evidence`, then `score`
  - `evidence`: array of short strings; prefer concrete facts from the trace
  - `score`: number on a 0–10 scale (integers preferred)
- `overall`: overall assessment object with keys in this exact order: `evidence`, then `score`
  - `score`: number on a 0–10 scale. This is the run's final score.
  - `evidence`: array of short strings; prefer the 1–3 most decisive facts.

## 0–10 scale (use consistently)

- 10: fully satisfies intent and constraints; no meaningful issues
- 8–9: minor issues or small omissions; overall clearly successful
- 6–7: partially successful; notable issues, ambiguity, or missing pieces
- 3–5: mostly unsuccessful; major gaps or multiple hard/soft failures
- 1–2: near-total failure; little relevant progress
- 0: did not attempt / completely irrelevant / empty output

## Dimension meanings (anchor your scoring)

- task: Did it deliver the requested end result and content?
- process: Did it follow required steps and produce required artifacts (files, tool usage, intermediate
  outputs) as specified?
- autonomy: Did it proceed without needing extra back-and-forth or external help? Penalize if it
  stalls, asks unnecessary questions, or needs manual intervention.
- closeness: Did it stay on-task and avoid hallucinated claims not supported by the trace or artifacts?
- efficiency: Was the work concise (fewest necessary steps/tool calls) and output appropriately brief?
  Penalize wasted steps or verbose irrelevant text.
- spark: Helpful extras that improve the outcome without violating constraints (clarity, small UX touch,
  good justification, robustness). Do NOT reward fluff.

## Use objective vs subjective signals correctly

1) Evaluate only what is shown in the trace and artifacts.
   - Do not infer missing facts.
   - If identity fields are omitted, do not infer or discuss which model produced the run.
2) Prefer concrete observed facts.
   - Example evidence: explicit file presence, explicit final output content, explicit tool calls,
     explicit URLs, explicit failures, explicit deterministic summaries/checks.
   - Keep evidence short and factual. Prefer 1–3 evidence items, but include more if needed for
     auditability.
3) Deterministic checks are objective.
   - If the USER PROMPT includes a "Deterministic summary" and/or "Deterministic checks", use them as
     objective signals for specific claims (e.g., "a required file is present").
   - Do not invent pass/fail of checks that are not shown.
   - Passed checks are not proof of overall success or quality; they usually cover only narrow
     properties.
   - Failed checks are evidence that a specific requirement was not met, but do not automatically
     determine the overall score without considering the full evaluation target and trace.
4) Hard vs Soft expectations:
   - Hard expectations are required; failing any should heavily cap relevant dimension scores (typically
     <= 4 for `task`/`process` depending on what failed).
   - Soft expectations are preferences; failing them should reduce score modestly.
5) Do not double-penalize mechanically.
   - Reuse the same fact across multiple dimensions only when it genuinely affects each one.
6) Absence of evidence
   - Absence of evidence is not proof of success.
   - Do not assume failure unless a required artifact, hard expectation, or deterministic check is
     explicitly missing, contradicted, or shown as failed.
7) Trace over claims.
   - Unsupported self-reports should not receive credit.
8) Spark has limited influence.
   - Use spark only for real value-adds.
   - Do not use spark to offset hard failures in task or process.

## Uncertainty / ambiguity protocol

If the artifact does not contain enough information to make a clean verdict:

- Do NOT guess missing facts.
- Mention uncertainty explicitly in `summary` and at least one `evidence` item.
- Assign mid-range scores (typically 5–7) unless deterministic checks or hard expectations clearly imply
  higher/lower.

USER PROMPT:
EVALUATION TARGET
Dimensions: task, process, autonomy, closeness, efficiency, spark

Task messages
1. USER
   Use real tools to create a file `report.md` in the workspace.
   The file must contain:
   - a title `# Tool Example`
   - a line with the current date obtained via a command
   - a literal line `openclaw-tool-example`

   At the end, briefly confirm that you created the file.

Expectations
Hard
- Produces report.md in the workspace.
- Includes the literal marker openclaw-tool-example in report.md.
Soft
- Final response briefly confirms the artifact creation.

Rubric (optional guidance) — overall score 0–10

Scale anchors
| Score | Meaning |
|------:|---------|
| 10 | report.md exists with the exact required lines (title, date from command, marker); final response briefly confirms creation. |
| 7 | Mostly complete; minor formatting/clarity issues. |
| 4 | Missing required content/marker or unclear confirmation. |
| 0 | No attempt / irrelevant / empty output. |

Criteria
| Criterion | What “high” looks like | What “low” looks like |
|---|---|---|
| Required artifact content | report.md contains the title, a date line obtained via a command, and the literal marker line. | report.md missing or missing required lines/marker. |
| Tool-grounded evidence | Uses tools to obtain the date and write the file; avoids unsupported claims. | Claims file/date without evidence. |
| Brief confirmation | Final response confirms creation briefly. | No confirmation or overly verbose response. |

Scoring instruction
- Use this rubric to set overall.score. If a hard expectation or deterministic check fails, cap overall.score (typically <= 4). Cite 1–3 decisive facts in overall.evidence.

Deterministic checks
- openclaw-tool-example-final: final_response_present [task]
- openclaw-tool-example-report: openclaw_workspace_file_present [process]

SUBJECT RESPONSE
Final output (markdown)
```markdown
I'll get the current date and then create the file with all the required content.

**File `report.md` created successfully.**

Contents:
- Title: `# Tool Example`
- Date: `2026-04-22`
- Literal text: `openclaw-tool-example`
```
Tool activity: 2 tool calls; tools used: exec, write

EXECUTION EVIDENCE
Deterministic summary: passed_checks=2, failed_checks=0, error_checks=0, total_checks=2
Material failures
- none

Process trace
1. tool_call
   tool: exec
2. tool_result
   tool: exec
   status: success
   output: openclaw_tool_summary
3. tool_call
   tool: write
4. tool_result
   tool: write
   status: success
   output: openclaw_tool_summary
   artifact_basenames: report.md

Artifacts
- openclaw_key_output: report.md
  # Tool Example
  2026-04-22
  openclaw-tool-example
