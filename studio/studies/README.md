# Study catalog

Five demo studies that together exercise the capabilities of the study
environment, plus the tutorial study used by `/setup`. Each subdirectory is a
self-contained study: `study.yaml` plus one `tasks/<id>.yaml` per task.
Shared fragments (NASA-TLX, attention check) live in `_lib/` and are pulled
in via `$ref:`.

| Study | Mode | VAs | What it demonstrates |
|---|---|---|---|
| [demo-singleplayer](demo-singleplayer/study.yaml) | singleplayer | 1 (PODIUM) | 8 task types (info, single/multi choice, likert, slider, number input, free text, VA interaction), 4 ground-truth kinds, auto+manual+required steps, world-state reset, conditional flow (branch + attention-check drop), Latin-square counterbalancing, randomize-within, params, per-language prompts, optional tasks, timers, screen+audio recording with transcription, Prolific-style completion |
| [demo-multiplayer](demo-multiplayer/study.yaml) | multiplayer (2) | 1 (PODIUM) | Cohorts: lobby + `participants_required`, selectable roles with capacity/colors, cohort code minting, per-role prompts, one shared world, chat/weights/drag auto-steps, advance policies **all / first / admin+timeout**, per-participant audio, multi-POV replay |
| [demo-wizard-of-oz](demo-wizard-of-oz/study.yaml) | multiplayer (2) | 1 (PODIUM) | Wizard-of-Oz: `wizard_panel` role, per-role briefing (`prompt_md_by_role`), per-role world state (`by_role`), wizard-paced advance, trust + manipulation-check questions, mandatory deception debrief |
| [demo-two-vas](demo-two-vas/study.yaml) | singleplayer | 2 (PODIUM + Voyager 2) | Multi-VA: `va_systems` + per-task `va_system` binding, `capture_state` against two different state vocabularies, random block order, cross-tool comparison, per-study dataset selection (Voyager's iframe URL carries `?dataset=penguins`) |
| [demo-proactiveva](demo-proactiveva/study.yaml) | singleplayer | 1 (ProactiveVA) | Proactive mixed-initiative: detector agents watch the interaction stream, an LLM planner pushes suggestions, participants accept/dismiss them (`accept_suggestion`/`reject_suggestion` auto-steps), notes as `capture_state` answers, trust questions about proactive timing |
| [starter-tutorial](starter-tutorial/study.yaml) | singleplayer | 1 (Starter VA, spawned) | The `/setup` tutorial's companion study — spawn-per-session (`spawn_cmd`), the minimal end-to-end flow |

All demo studies embed the **hosted** PODIUM/Voyager/ProactiveVA (literal URLs,
so they run from the cluster and from a local checkout alike);
`room_per_session` isolates each session's world on the shared deployments. The starter-tutorial study
instead **spawns** its VA per session — the second integration path.

## Running a study on Prolific

1. **Declare completion** in `study.yaml`:

   ```yaml
   completion_code: MY-CODE-123          # the code Prolific gave you
   completion_redirect_url: prolific     # shorthand for Prolific's completion URL
   ```

   With the redirect set, finishers are sent to
   `https://app.prolific.com/submissions/complete?cc=MY-CODE-123`; the
   thank-you page also always shows the code as copyable text, so nobody is
   stranded if the redirect is blocked. (Leave the redirect out to only show
   the code.)

2. **Mint a code** on the study's admin page and paste the *Prolific* variant
   of the join link as the study URL on Prolific:

   ```
   https://<your-host>/s/<CODE>?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
   ```

   Prolific substitutes the placeholders per participant. Studio stores the
   PID as the participant's `external_id` (plus the raw params in
   `recruitment`) — it survives page refreshes, the preflight page, manual
   code entry, and mid-study resume.

3. **Reward participants**: the PID appears as **External ID** on the admin
   session page, in the participant journey, and as the `external_id` column
   in the CSV/Parquet/JSONL exports — match it against Prolific's submission
   list to approve/reward exactly the people in your data. A PID that already
   finished the study is bounced back to the finish page instead of starting
   a second (double-paid) run.
