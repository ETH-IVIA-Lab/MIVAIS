"""Scoring plugin namespace.

Studies declare custom scoring with:

    ground_truth:
      type: custom
      value: studio.scoring.custom.car_ranking:score   # module.path:callable

Drop your scorer at ``studio/scoring/custom/<name>.py`` and reference it from
the study YAML. The callable signature is described in
:mod:`studio.orchestrator.scoring`.
"""
