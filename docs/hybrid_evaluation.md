# Hybrid Evaluation

Hybrid evaluation combines:

- deterministic evaluation outputs
- aggregated judge outputs

It produces a final evaluation artifact without re-running the model or the judge.

## Why A Separate Layer Exists

The framework keeps deterministic scoring and judge scoring separate because they answer
different questions:

- deterministic checks are stable and auditable
- judge outputs capture semantic quality that is hard to express as assertions

The final hybrid layer makes the policy explicit instead of hiding it.

## Final Result Shape

```json
{
  "case_id": "example_case",
  "run_id": "run_001",
  "deterministic_dimensions": {
    "task": 0.0,
    "process": 10.0,
    "autonomy": null,
    "closeness": null,
    "efficiency": null,
    "spark": null
  },
  "judge_dimensions": {
    "task": 8.0,
    "process": 6.0,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 5.0,
    "spark": 6.0
  },
  "final_dimensions": {
    "task": 5.6,
    "process": 7.6,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 5.0,
    "spark": 6.0
  },
  "final_score": 6.32,
  "security": {
    "verdict": "not_evaluated",
    "warnings": []
  },
  "warnings": []
}
```

## Per-Dimension Policy

V1 supports these policies:

- `judge_only`
- `deterministic_only`
- `weighted`

The default is `judge_only`.

That means the judge remains the prevailing source unless a dimension explicitly overrides the
policy.

## Example Aggregation Config

```yaml
final_aggregation:
  default_policy: judge_only
  dimensions:
    task:
      policy: weighted
      judge_weight: 0.7
      deterministic_weight: 0.3
    process:
      policy: weighted
      judge_weight: 0.6
      deterministic_weight: 0.4
  final_score_weights:
    task: 0.3
    process: 0.15
    autonomy: 0.2
    closeness: 0.1
    efficiency: 0.15
    spark: 0.1
```

## Fallback Rule

If deterministic scoring is missing for a dimension, hybrid aggregation falls back to the
judge and records a warning.

Example:

```json
{
  "dimension": "task",
  "policy": "weighted",
  "judge_score": 7.0,
  "deterministic_score": null,
  "final_score": 7.0,
  "warning": "Deterministic score missing for 'task'; judge score used as fallback."
}
```

## Resolution Metadata

The final result also stores per-dimension resolution metadata so users can inspect what
happened during aggregation.

Example:

```json
{
  "task": {
    "policy": "weighted",
    "source_used": "weighted",
    "judge_score": 8.0,
    "deterministic_score": 0.0,
    "final_score": 5.6
  }
}
```

## Security Block

The final artifact keeps a separate security block:

```json
{
  "security": {
    "verdict": "passed",
    "warnings": []
  }
}
```

This is kept visible instead of being hidden inside the numerical score.

## Related Reading

- [Configuration](configuration.md)
- [Judge results](judge_results.md)
- [Run artifacts](run_artifacts.md)
