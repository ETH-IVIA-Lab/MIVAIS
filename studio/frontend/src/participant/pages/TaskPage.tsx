import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost, ApiError } from "../../lib/api";
import type { TaskPageResponse } from "../../lib/types";
import { AudioIndicator } from "../components/AudioIndicator";
import { BiometricIndicator } from "../components/BiometricIndicator";
import { CohortWaitingBanner } from "../components/CohortWaitingBanner";
import { TaskAnswerForm, type AnswerValue } from "../components/TaskAnswerForm";
import { TaskStepsList } from "../components/TaskStepsList";
import { WizardPanel } from "../components/WizardPanel";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { useHeartRateMonitor } from "../hooks/useHeartRateMonitor";
import { useMultiplayerTaskSync } from "../hooks/useMultiplayerTaskSync";
import { useTaskSteps } from "../hooks/useTaskSteps";
import { useVaEventBridge } from "../hooks/useVaEventBridge";
import { InterruptedView } from "./InterruptedPage";
import "../../styles/task.css";

function formatTimer(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const r = seconds % 60;
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

export function TaskPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<TaskPageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const currentAnswerRef = useRef<AnswerValue>(null);

  const load = useCallback(async () => {
    const res = await apiGet<TaskPageResponse>("/api/p/task");
    if (res.next) {
      navigate(res.next, { replace: true });
      return;
    }
    setData(res);
  }, [navigate]);

  useEffect(() => {
    load();
  }, [load]);

  const task = data?.task;
  const study = data?.study;
  const ui = data?.ui ?? {};
  const audioMode = (study?.recording?.audio as string | undefined) ?? "none";
  const audioRecorder = useAudioRecorder(data && !data.interrupted ? audioMode : undefined);
  const biometricEnabled = !!study?.recording?.biometric;
  const heartRate = useHeartRateMonitor();

  const { checked: checkedSteps, toggle: toggleStep, refresh: refreshSteps } = useTaskSteps(task?.id);
  useVaEventBridge(data?.iframe_url, refreshSteps);
  const cohortEtaSeconds = useMultiplayerTaskSync(study?.mode === "multiplayer", data?.task_index, load);

  const handleSubmit = useCallback(
    async (action: "submit" | "skip" | "timeout", value: AnswerValue) => {
      setBusy(true);
      setSubmitError(null);
      try {
        const body: Record<string, unknown> = { action };
        if (action !== "skip") body.value = value;
        await apiPost("/api/p/task", body);
        await load();
      } catch (err) {
        setSubmitError(err instanceof ApiError ? err.message : "Something went wrong.");
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

 
  useEffect(() => {
    const secs = task?.timer_seconds;
    if (!ui.show_timer || !secs) {
      setRemaining(null);
      return;
    }
    setRemaining(secs);
    const tick = window.setInterval(() => {
      setRemaining((r) => {
        if (r === null) return null;
        const next = r - 1;
        if (next <= 0) {
          window.clearInterval(tick);
          handleSubmit("timeout", currentAnswerRef.current);
          return 0;
        }
        return next;
      });
    }, 1000);
    return () => window.clearInterval(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  function toggleFullscreen() {
    if (!stageRef.current) return;
    if (!document.fullscreenElement) stageRef.current.requestFullscreen?.();
    else document.exitFullscreen?.();
  }

  if (!data) return null;
  if (data.interrupted) return <InterruptedView />;
  if (!task || !study) return null;

  const isVa = !!(data.iframe_url && (task.type === "va_interaction" || task.with_va));
  const totalTasks = data.total_tasks ?? 1;
  const taskIndex = data.task_index ?? 0;
  const stepsVisible = !!ui.task_steps_visible && !!task.task_steps?.length;

  const stepsList = task.task_steps ? (
    <TaskStepsList steps={task.task_steps} checked={checkedSteps} onToggle={toggleStep} />
  ) : null;

  const promptBody = (
    <div className="prose small" dangerouslySetInnerHTML={{ __html: (task.type === "info_screen" ? task.body_html : task.prompt_html) || "" }} />
  );

  const taskVideo = task.type === "info_screen" && task.video_url ? (
    <video className="task-video" src={task.video_url} controls preload="metadata" style={{ width: "100%", borderRadius: 8, marginBottom: 14 }} />
  ) : null;

  const answerForm = (
    <TaskAnswerForm
      key={task.id}
      task={task}
      checkedSteps={checkedSteps}
      busy={busy}
      onSubmit={handleSubmit}
      onAnswerChange={(v) => {
        currentAnswerRef.current = v;
      }}
    />
  );

  return (
    <div>
      <AudioIndicator state={audioRecorder.state} queuedCount={audioRecorder.queuedCount} />
      {biometricEnabled && <BiometricIndicator status={heartRate.status} bpm={heartRate.bpm} />}
      <div className={`task-shell ${isVa ? "is-va" : ""}`}>
        {data.waiting_for_cohort && <CohortWaitingBanner secondsRemaining={cohortEtaSeconds} />}

        <header className="task-bar">
          {!!ui.show_progress_bar && (
            <div className="progress">
              <span className="progress-label muted small">
                Task {taskIndex + 1} of {totalTasks}
              </span>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${Math.floor(((taskIndex + 1) / totalTasks) * 100)}%` }} />
              </div>
            </div>
          )}
          <div className="task-bar-actions">
            {remaining !== null && (
              <div className={`timer ${remaining <= 10 ? "warning" : ""}`}>
                <span className="timer-value">{formatTimer(Math.max(remaining, 0))}</span>
              </div>
            )}
            {isVa && (
              <button type="button" className="btn ghost" title="Fullscreen the VA system" onClick={toggleFullscreen}>
                <span className="icon">⤢</span> Fullscreen
              </button>
            )}
          </div>
        </header>

        {submitError && (
          <div className="alert error" style={{ margin: "12px 22px" }}>
            {submitError}
          </div>
        )}

        {isVa ? (
          <div className="va-body">
            <div className={`va-stage ${isFullscreen ? "is-fullscreen" : ""}`} id="va-stage" ref={stageRef}>
              <iframe className="va-iframe" id="va-iframe" src={data.iframe_url ?? undefined} title="Visual Analytics System" allow="fullscreen" />
            </div>
            <aside className="va-side">
              <div className="va-side-scroll">
                <p className="task-eyebrow">{task.id}</p>
                {taskVideo}
                {promptBody}
                {answerForm}
                {stepsVisible && (
                  <section className="va-side-steps">
                    <h4>Steps</h4>
                    {stepsList}
                  </section>
                )}
              </div>
            </aside>
          </div>
        ) : (
          <div className="task-body classic">
            <section className="task-prompt">
              <p className="task-eyebrow">{task.id}</p>
              {taskVideo}
              {promptBody}
            </section>
            <section className="task-main">{answerForm}</section>
            {stepsVisible && (
              <aside className="task-steps">
                <h3>Steps</h3>
                {stepsList}
              </aside>
            )}
          </div>
        )}
      </div>

      {data.is_wizard && <WizardPanel />}
    </div>
  );
}
