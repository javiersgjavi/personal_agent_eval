# Run Artifacts

`personal_agent_eval` defines a canonical JSON-serializable run artifact schema in V1 for
recording the result of one runner execution.

The V1 schema is provider-aware and runner-agnostic:

- It records canonical identity fields for the run, including `schema_version`, `run_id`,
  `case_id`, `suite_id`, `run_profile_id`, and `runner_type`.
- It separates requested execution metadata from provider-returned metadata.
- It stores normalized usage metrics plus raw provider usage when available.
- It represents the execution trace as an ordered event sequence.
- It stores output artifact references and metadata, not embedded file blobs.
- It includes an explicit structured error object for any non-success terminal status.
- It reserves `runner_metadata` for runner-specific extension fields without changing the
  canonical top-level structure.

V1 terminal statuses are:

- `success`
- `failed`
- `timed_out`
- `invalid`
- `provider_error`

For OpenRouter-backed runs, the schema can record:

- requested model and requested gateway in the request metadata
- gateway, provider name, provider model id, request id, response id, finish reason, and
  native finish reason in provider metadata

The schema package only defines the artifact surface. It does not implement runner
execution, judge logic, fingerprinting, or artifact storage.
