"""Custom metric plugins, mirroring the custom-scorer convention.

Drop ``<name>.py`` here and reference it from a study YAML::

    metrics:
      - id: my_metric
        kind: python
        module: studio.metrics.custom.<name>:compute
        params: { ... }

The callable receives ``(events, params)`` — the participant's time-ordered
event dicts (already scoped to `task:` if set) and the YAML params — and
returns a number, or ``(number, detail_dict)``.
"""
