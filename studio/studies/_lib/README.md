# Shared task library

YAML fragments that any study can import via `$ref`.

```yaml
blocks:
  - id: workload
    tasks:
      - $ref: ../_lib/tasks/nasa-tlx.yaml          # relative to study dir
      - $ref: _lib/tasks/attention-check.yaml      # relative to studies/ root
```

The loader hashes every `$ref` target into the study's manifest, so the
study's overall digest changes when any imported fragment changes. Paths
outside `settings.studies_dir` are refused — `$ref` cannot reach
arbitrary files on disk.

You can shallow-override imported fields by listing them next to `$ref:`:

```yaml
- $ref: ../_lib/tasks/nasa-tlx.yaml
  prompt_md: "Rate the **PODIUM exercise** you just completed:"
  tags: [nasa-tlx, podium]
```

## What's here

- **`tasks/nasa-tlx.yaml`** — NASA Task Load Index (6 dimensions, 7-point likert).
  The classic post-task workload questionnaire used across HCI.
- **`tasks/attention-check.yaml`** — a simple "pick red" attention check.
  Pair with a `next:` branch that drops failed participants:

  ```yaml
  - $ref: _lib/tasks/attention-check.yaml
    next:
      - when: "not correct"
        goto: { action: drop }
  ```
