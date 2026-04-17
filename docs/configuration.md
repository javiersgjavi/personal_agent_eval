# Configuration Roles

`personal_agent_eval` uses four YAML config file types in V1. Each file must declare
`schema_version: 1` and is loaded through an explicit config loader that returns a validated,
normalized object.

## Test Configs

- Path: `cases/<case_id>/test.yaml`
- Loader: `load_test_config(path)`
- Purpose: define one evaluation case, including the runner selection, input messages,
  expectations, deterministic checks, tags, and metadata

V1 test configs support explicit input sections, full message sequences, inline messages,
external message references, declarative deterministic checks, and Python hook references.
Any relative file references resolve relative to the `test.yaml` file.

## Suite Configs

- Path: `suites/<suite_id>.yaml`
- Loader: `load_suite_config(path)`
- Purpose: group models with a case selection policy and suite-level metadata

Suites declare which models participate in a run and which cases or tags should be included
or excluded.

## Run Profiles

- Path: `run_profiles/<profile_id>.yaml`
- Loader: `load_run_profile(path)`
- Purpose: define execution-time defaults, model overrides, and execution policy settings

Run profiles are the canonical place for concurrency and fail-fast controls. They do not
implement runner logic themselves; they only define validated configuration.

## Evaluation Profiles

- Path: `evaluation_profiles/<profile_id>.yaml`
- Loader: `load_evaluation_profile(path)`
- Purpose: define judges, judge runs, aggregation rules, anchors, and security policy

Evaluation profiles describe how scoring should be configured without implementing judge
execution, fingerprinting, or artifact storage.
