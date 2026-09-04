import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../../lib/api";

export function useAdminSession() {
  const [username, setUsername] = useState<string | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<{ username: string | null }>("/api/admin/me");
      setUsername(data.username);
    } catch {
      setUsername(null);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { username, loading: username === undefined, refresh };
}
