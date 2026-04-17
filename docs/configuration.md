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

## Discovery And Suite Expansion

- Cases are discovered from a supplied workspace root under `cases/<case_id>/test.yaml`
- Suites are discovered from a supplied workspace root under `suites/<suite_id>.yaml`
- Duplicate discovered `case_id` values are a hard error
- Any suite reference to a missing `case_id` in `include_case_ids` or `exclude_case_ids`
  is a hard error
- `include_case_ids` has priority over tag filters and exclude lists
- Tag-based selection matches when a case has any requested tag
- Expanded suite case lists are deterministic and sorted by `case_id`

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

## Related Docs

- [Run Artifacts](run_artifacts.md): canonical JSON-serializable schema for recorded runner
  executions
