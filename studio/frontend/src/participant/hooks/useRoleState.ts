import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import type { RoleOption, RoleStateResponse } from "../../lib/types";

export function useRoleState(enabled: boolean) {
  const [roles, setRoles] = useState<RoleOption[] | null>(null);
  const [redirect, setRedirect] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await apiGet<RoleStateResponse>("/api/p/role/state");
        if (cancelled) return;
        if (data.redirect) {
          setRedirect(data.redirect);
          return;
        }
        if (data.roles) setRoles(data.roles);
      } catch {
        // transient network hiccup; retry next tick
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return { roles, redirect };
}
