# Config Model

`personal_agent_eval` is driven by five YAML configuration surfaces. Each one answers a different question, and together they define a complete benchmark **campaign**.

| Config type | File path | Answers |
|---|---|---|
| Test case | `configs/cases/<case_id>/test.yaml` | _What_ to test |
| Suite | `configs/suites/<suite_id>.yaml` | _Which_ cases and models |
| Run profile | `configs/run_profiles/<profile_id>.yaml` | _How_ to execute |
| Evaluation profile | `configs/evaluation_profiles/<profile_id>.yaml` | _How_ to judge |
| OpenClaw agent | `configs/agents/<agent_id>/agent.yaml` + `workspace/` | _Which_ reusable agent workspace |

---

## How the four core configs relate

```mermaid
flowchart TD
    T["<b>test.yaml</b><br/>runner · input · expectations · checks · rubric"]
    S["<b>suite.yaml</b><br/>cases × models"]
    R["<b>run_profile.yaml</b><br/>temperature · max_tokens · repetitions"]
    E["<b>evaluation_profile.yaml</b><br/>judge · aggregation · dimensions"]
    W["<b>pae run-eval</b><br/>--suite · --run-profile · --evaluation-profile"]
    A["<b>RunArtifact</b><br/>per model × case × run_N"]
    F["<b>FinalEvaluationResult</b><br/>deterministic + judge score"]
    P["<b>Report</b><br/>pae report"]

    T -->|"selected by id / tag"| S
    S -->|"--suite"| W
    R -->|"--run-profile"| W
    E -->|"--evaluation-profile"| W
    W -->|"llm_probe or openclaw runner"| A
    A -->|"deterministic + judge"| F
    F --> P

    classDef cfg   fill:#E8EAF6,stroke:#5C6BC0,color:#1A237E
    classDef orch  fill:#DCE3FF,stroke:#5C6BC0,color:#1A237E
    classDef art   fill:#E8F5E9,stroke:#43A047,color:#1B5E20

    class T,S,R,E cfg
    class W orch
    class A,F,P art
```

---

## OpenClaw execution flow

When a case uses `runner.type: openclaw`, two extra config surfaces come into play: the agent definition and the `openclaw:` block in the run profile.

```mermaid
flowchart TD
    TC["<b>test.yaml</b><br/>runner.type: openclaw<br/>input · expectations · checks"]
    RP["<b>run_profile.yaml</b><br/>openclaw.agent_id<br/>openclaw.image · timeout"]
    AC["<b>configs/agents/&lt;agent_id&gt;/</b><br/>agent.yaml<br/>workspace/ template"]
    FP["<b>Fingerprint check</b><br/>SHA-256 of all inputs<br/>+ agent + workspace"]
    WS["<b>Ephemeral workspace</b><br/>temp dir · workspace copied<br/>openclaw.json generated"]
    DC["<b>docker run &lt;image&gt;</b><br/>openclaw CLI inside container<br/>OPENROUTER_API_KEY forwarded"]
    RA["<b>RunArtifact</b><br/>runner_metadata.openclaw<br/>workspace diff · logs · key outputs"]
    DE["<b>Deterministic checks</b><br/>openclaw_workspace_file_present<br/>file_contains · etc."]
    JU["<b>Judge</b><br/>compact subject view<br/>task + response + evidence"]
    FE["<b>FinalEvaluationResult</b><br/>hybrid score 0–10"]

    TC --> FP
    RP --> FP
    AC --> FP
    FP -->|"cache miss → execute"| WS
    WS -->|"docker run"| DC
    DC -->|"captures"| RA
    RA --> DE
    RA --> JU
    DE --> FE
    JU --> FE

    classDef cfg   fill:#E8EAF6,stroke:#5C6BC0,color:#1A237E
    classDef orch  fill:#DCE3FF,stroke:#5C6BC0,color:#1A237E
    classDef art   fill:#E8F5E9,stroke:#43A047,color:#1B5E20
    classDef exec  fill:#FFF8E1,stroke:#F9A825,color:#5D4037

    class TC,RP,AC cfg
    class FP,WS,DC exec
    class RA,DE,JU,FE art
```

---

## llm_probe execution flow

For `runner.type: llm_probe`, the runner calls OpenRouter directly and manages a tool-use loop until the model produces a final response or reaches `max_turns`.

```mermaid
flowchart TD
    TC["<b>test.yaml</b><br/>runner.type: llm_probe<br/>input.messages<br/>input.context.llm_probe.tools"]
    RP["<b>run_profile.yaml</b><br/>temperature · max_tokens<br/>max_turns · retries"]
    OR["<b>OpenRouter API</b><br/>model call with tool definitions"]
    TL["<b>Tool execution loop</b><br/>exec_shell · read_file · write_file<br/>web_search · …"]
    RA["<b>RunArtifact</b><br/>message trace · tool calls<br/>token usage · final output"]
    DE["<b>Deterministic checks</b><br/>final_response_present<br/>file_contains · tool_call_count · etc."]
    JU["<b>Judge</b><br/>compact subject view<br/>task + response + tool activity"]
    FE["<b>FinalEvaluationResult</b><br/>hybrid score 0–10"]

    TC --> OR
    RP --> OR
    OR -->|"tool_call → tool_result loop"| TL
    TL --> OR
    OR -->|"finish"| RA
    RA --> DE
    RA --> JU
    DE --> FE
    JU --> FE

    classDef cfg   fill:#E8EAF6,stroke:#5C6BC0,color:#1A237E
    classDef exec  fill:#FFF8E1,stroke:#F9A825,color:#5D4037
    classDef art   fill:#E8F5E9,stroke:#43A047,color:#1B5E20

    class TC,RP cfg
    class OR,TL exec
    class RA,DE,JU,FE art
```

---

## What each config controls

### `test.yaml` — the atomic test case

Defines one scenario in full isolation. The same case can be included in multiple suites and run against multiple models without modification.

```yaml
schema_version: 1
case_id: llm_probe_tool_example
title: "llm_probe tool example"
runner:
  type: llm_probe                 # or: openclaw
input:
  messages:
    - role: user
      content: |
        Use real tools to create a file...
  context:
    llm_probe:
      tools:
        - exec_shell
        - write_file
        - read_file
expectations:
  hard_expectations:
    - text: Uses tools to obtain the content instead of inventing it.
  soft_expectations:
    - text: Response is brief and clearly confirms the final file content.
rubric:
  version: 1
  scale:
    min: 0
    max: 10
    anchors:
      "10": All required steps completed; artifacts present; confirmation clear.
      "0": No attempt or irrelevant output.
  criteria:
    - name: Tool-grounded correctness
      what_good_looks_like: Uses required tools and reports observed results.
      what_bad_looks_like: Invents results or skips required steps.
deterministic_checks:
  - check_id: final-response-present
    dimensions: [task]
    declarative:
      kind: final_response_present
  - check_id: file-written
    dimensions: [process]
    declarative:
      kind: file_contains
      path: /tmp/expected_output.txt
      text: expected-marker
tags:
  - example
  - llm_probe
```

---

### `suite.yaml` — the campaign scope

Lists which cases and which models form the benchmark.

```yaml
schema_version: 1
suite_id: llm_probe_examples
title: "llm_probe runnable examples"
models:
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
    label: minimax/minimax-m2.7
case_selection:
  include_case_ids:
    - llm_probe_tool_example
    - llm_probe_browser_example
```

You can select cases by tag instead of (or in addition to) explicit IDs:

```yaml
case_selection:
  include_tags: [example]
  exclude_tags: [slow]
```

---

### `run_profile.yaml` — execution policy

Controls how the runner calls the model. A fingerprint of the effective execution settings scopes campaign directories.

```yaml
schema_version: 1
run_profile_id: llm_probe_examples
runner_defaults:
  temperature: 0
  timeout_seconds: 90
  max_tokens: 768
  max_turns: 6
  retries: 0
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
  fail_fast: true
  stop_on_runner_error: true
```

For OpenClaw, add the `openclaw:` block:

```yaml
schema_version: 1
run_profile_id: openclaw_examples
openclaw:
  agent_id: basic_agent
  image: ghcr.io/openclaw/openclaw:2026.4.15
  timeout_seconds: 300
execution_policy:
  max_concurrency: 1
  run_repetitions: 1
  fail_fast: true
```

---

### `evaluation_profile.yaml` — judge policy

Defines one or more LLM judges, how repeated judge runs aggregate, and security controls.

```yaml
schema_version: 1
evaluation_profile_id: judge_gpt54
judges:
  - judge_id: gpt54_judge
    type: llm_probe
    model: openai/gpt-5.4-mini
judge_runs:
  - judge_run_id: gpt54_single
    judge_id: gpt54_judge
    repetitions: 1
aggregation:
  method: median
security_policy:
  allow_local_python_hooks: false
  redact_secrets: true
```

!!! note "final_score"
    `final_score` is the judge's holistic `overall.score` (0–10). Deterministic checks are preserved as supporting evidence for the judge and for debugging, but they do not compute the top-level score.

---

### `configs/agents/<agent_id>/` — reusable OpenClaw agent

```text
configs/agents/basic_agent/
  agent.yaml        ← agent identity, model defaults, sandbox settings
  workspace/
    AGENTS.md       ← workspace template (copied to every run)
    SOUL.md
```

---

## Campaign storage layout

```text
outputs/
├── charts/
│   └── {evaluation_profile_id}/
│       └── score_cost.png
├── runs/
│   └── suit_{suite_id}/
│       └── run_profile_{fp6}/
│           └── {model_id}/
│               └── {case_id}/
│                   ├── run_1.json
│                   ├── run_1.fingerprint_input.json
│                   └── run_2.json          ← when run_repetitions > 1
└── evaluations/
    └── suit_{suite_id}/
        └── evaluation_profile_{fp6}/
            └── eval_profile_{eval_id}_{fp6}/
                └── {model_id}/
                    └── {case_id}/
                        ├── evaluation_result_summary_1.md
                        ├── judge_1.prompt.debug.md
                        └── raw_outputs/
                            ├── final_result_1.json
                            ├── judge_1.json
                            └── judge_1.prompt.user.json
```

`fp6` is the first 6 characters of the SHA-256 fingerprint. → [Fingerprints & reuse](fingerprints.md)
