import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../../lib/api";
import type { TaskStepsResponse } from "../../lib/types";

export function useTaskSteps(taskId: string | undefined) {
  const [checked, setChecked] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<TaskStepsResponse>("/api/p/task/steps");
      setChecked(new Set(data.checked));
    } catch {
      // transient network hiccup; next poll will catch up
    }
  }, []);

  useEffect(() => {
    if (!taskId) return;
    refresh();
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  }, [taskId, refresh]);

  const toggle = useCallback(async (stepId: string, isChecked: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (isChecked) next.add(stepId);
      else next.delete(stepId);
      return next;
    });
    try {
      const data = await apiPost<TaskStepsResponse>("/api/p/task/check_step", {
        step_id: stepId,
        checked: isChecked,
      });
      setChecked(new Set(data.checked));
    } catch {
      // offline tolerance — local toggle stays
    }
  }, []);

  return { checked, toggle, refresh };
}
