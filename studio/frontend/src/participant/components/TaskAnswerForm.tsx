import { useEffect, useState, type FormEvent } from "react";
import type { Task } from "../../lib/types";

export type AnswerValue = string | number | string[] | Record<string, number> | null;

function rangeInclusive(min: number, max: number, step: number): number[] {
  const out: number[] = [];
  for (let v = min; v <= max; v += step) out.push(v);
  return out;
}

function defaultValueFor(task: Task): AnswerValue {
  switch (task.type) {
    case "multi_choice":
      return [];
    case "likert":
      return {};
    case "slider": {
      const lo = task.min ?? 0;
      const hi = task.max ?? 100;
      return task.default_value ?? (lo + hi) / 2;
    }
    default:
      return "";
  }
}

export function TaskAnswerForm({
  task,
  checkedSteps,
  busy,
  onSubmit,
  onAnswerChange,
}: {
  task: Task;
  checkedSteps: Set<string>;
  busy: boolean;
  onSubmit: (action: "submit" | "skip", value: AnswerValue) => void;
  onAnswerChange?: (value: AnswerValue) => void;
}) {
  const [value, setValue] = useState<AnswerValue>(() => defaultValueFor(task));

  useEffect(() => {
    onAnswerChange?.(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const requiredStepIds = (task.task_steps || []).filter((s) => s.required).map((s) => s.id);
  const stepsGateOk = requiredStepIds.every((id) => checkedSteps.has(id));

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit("submit", value);
  }

  return (
    <form onSubmit={handleSubmit} className="task-form">
      {task.type === "info_screen" && (
        <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
          {task.continue_label || "Continue"}
        </button>
      )}

      {task.type === "single_choice" && (
        <>
          <fieldset className="choices">
            {(task.options || []).map((opt) => (
              <label key={opt.id} className={`choice ${value === opt.id ? "selected" : ""}`}>
                <input
                  type="radio"
                  name="answer"
                  value={opt.id}
                  required
                  checked={value === opt.id}
                  onChange={() => setValue(opt.id)}
                />
                <span>{opt.label}</span>
              </label>
            ))}
          </fieldset>
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Submit
          </button>
        </>
      )}

      {task.type === "multi_choice" && (
        <>
          <fieldset className="choices">
            {(task.options || []).map((opt) => {
              const list = Array.isArray(value) ? value : [];
              const isChecked = list.includes(opt.id);
              return (
                <label key={opt.id} className={`choice ${isChecked ? "selected" : ""}`}>
                  <input
                    type="checkbox"
                    value={opt.id}
                    checked={isChecked}
                    onChange={(e) => {
                      setValue((prev) => {
                        const arr = Array.isArray(prev) ? prev : [];
                        return e.target.checked ? [...arr, opt.id] : arr.filter((x) => x !== opt.id);
                      });
                    }}
                  />
                  <span>{opt.label}</span>
                </label>
              );
            })}
          </fieldset>
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Submit
          </button>
        </>
      )}

      {task.type === "likert" && task.scale && (
        <>
          <div className="likert">
            <div className="likert-scale-head">
              <span className="muted small">{task.scale.min_label}</span>
              <span className="muted small">{task.scale.max_label}</span>
            </div>
            {(task.items || []).map((item) => {
              const scores = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<
                string,
                number
              >;
              return (
                <fieldset key={item.id} className="likert-row">
                  <legend>
                    {item.label}
                    {item.description && <span className="muted small"> — {item.description}</span>}
                  </legend>
                  <div className="likert-buttons">
                    {rangeInclusive(task.scale!.min, task.scale!.max, task.scale!.step).map((v) => (
                      <label key={v} className={scores[item.id] === v ? "selected" : ""}>
                        <input
                          type="radio"
                          name={`likert__${item.id}`}
                          value={v}
                          required
                          checked={scores[item.id] === v}
                          onChange={() => setValue((prev) => ({ ...(prev as Record<string, number>), [item.id]: v }))}
                        />
                        <span>{v}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              );
            })}
          </div>
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Submit
          </button>
        </>
      )}

      {task.type === "slider" && (
        <>
          <div className="slider-field">
            <div className="likert-scale-head">
              <span className="muted small">{task.min_label || String(task.min ?? 0)}</span>
              {task.show_value !== false && (
                <strong className="slider-value">
                  {typeof value === "number" ? value : task.default_value ?? ""}
                  {task.unit ? ` ${task.unit}` : ""}
                </strong>
              )}
              <span className="muted small">{task.max_label || String(task.max ?? 100)}</span>
            </div>
            <input
              type="range"
              min={task.min ?? 0}
              max={task.max ?? 100}
              step={task.step ?? 1}
              value={typeof value === "number" ? value : ((task.min ?? 0) + (task.max ?? 100)) / 2}
              onChange={(e) => setValue(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </div>
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Submit
          </button>
        </>
      )}

      {task.type === "number_input" && (
        <>
          <label className="field" style={{ maxWidth: 220 }}>
            <span className="muted small">Your answer{task.unit ? ` (${task.unit})` : ""}</span>
            <input
              type="number"
              min={task.min ?? undefined}
              max={task.max ?? undefined}
              step={task.step ?? 1}
              placeholder={task.placeholder || ""}
              value={typeof value === "number" ? value : typeof value === "string" ? value : ""}
              onChange={(e) => setValue(e.target.value === "" ? "" : Number(e.target.value))}
              required
            />
          </label>
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Submit
          </button>
        </>
      )}

      {task.type === "free_text" && (
        <>
          <textarea
            value={typeof value === "string" ? value : ""}
            onChange={(e) => setValue(e.target.value)}
            rows={task.rows || 4}
            minLength={task.min_chars || 0}
            maxLength={task.max_chars || 5000}
            placeholder={task.placeholder || ""}
            required
          />
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Submit
          </button>
        </>
      )}

      {task.type === "va_interaction" && (
        <div className="va-answer">
          {task.answer?.type === "text" && (
            <label className="field">
              <span className="muted small">Your answer</span>
              <textarea
                value={typeof value === "string" ? value : ""}
                onChange={(e) => setValue(e.target.value)}
                rows={3}
                required
              />
            </label>
          )}
          {task.answer?.type === "capture_state" && (
            <p className="muted small">
              When you submit, the value of <code>{task.answer.world_state_key}</code> is captured automatically
              from the VA.
            </p>
          )}
          {(!task.answer || (task.answer.type !== "text" && task.answer.type !== "capture_state")) && (
            <p className="muted small">Click when you are done with this task.</p>
          )}
          <button type="submit" className="btn primary" disabled={busy || !stepsGateOk}>
            Done with this task
          </button>
        </div>
      )}

      {task.optional && (
        <button type="button" className="btn ghost" disabled={busy} onClick={() => onSubmit("skip", null)}>
          Skip
        </button>
      )}
    </form>
  );
}
