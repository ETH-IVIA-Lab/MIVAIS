import type { TaskStep } from "../../lib/types";

export function TaskStepsList({
  steps,
  checked,
  onToggle,
}: {
  steps: TaskStep[];
  checked: Set<string>;
  onToggle: (stepId: string, checked: boolean) => void;
}) {
  return (
    <ol className="task-steps-list">
      {steps.map((step) => {
        const mode = step.mode || (step.auto_check_on ? "either" : "manual");
        const isChecked = checked.has(step.id);
        return (
          <li key={step.id} data-mode={mode} className={isChecked ? "checked" : ""}>
            <label>
              <input
                type="checkbox"
                checked={isChecked}
                disabled={mode === "auto"}
                onChange={(e) => onToggle(step.id, e.target.checked)}
              />
              <span>
                {step.label}
                {step.required && <span className="muted small"> (required)</span>}
                {mode === "auto" && <span className="chip auto-check">auto validated</span>}
                {mode === "either" && <span className="chip auto-check">auto or click</span>}
              </span>
            </label>
          </li>
        );
      })}
    </ol>
  );
}
