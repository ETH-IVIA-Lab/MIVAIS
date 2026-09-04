# Locales

Drop one JSON file per language code (`en.json`, `de.json`, `fr.json`, …). The
file is a flat object mapping the English source string to its translation:

```json
{
  "Sign in": "Anmelden",
  "Studies": "Studien",
  "Compare studies": "Studien vergleichen",
  "Cohort minted.": "Kohorte erstellt."
}
```

Missing keys fall back to the source string, so a partial translation is fine —
the platform never breaks on an unfinished locale.

Activate with `STUDIO_DEFAULT_LANG=de` in your `.env`. The participant flow's
content (consent text, prompts, options) is **not** translated by this layer —
those strings come from `study.yaml` and the study author decides how to
localise them (typically by writing per-language YAML variants or using
`{{ params.<key> }}` substitution).
