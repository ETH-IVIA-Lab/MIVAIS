/**
 * Thin fetchers for the `mivais` REST surface. Not every backend exposes
 * every one of these - callers only import
 * what their app's backend actually serves.
 */

export interface UserRoleInfo {
  role: string;
  description?: string;
  can_read?: string[];
  can_write?: string[];
  bus_subscribe_topics?: string[];
  bus_publish_topics?: string[];
}

export interface RecordingInfo {
  filename: string;
  size_bytes: number;
  created_at: string;
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  return (await res.json()) as T;
}

export async function fetchUsers(baseUrl = ""): Promise<UserRoleInfo[]> {
  const data = await getJSON<{ users: UserRoleInfo[] }>(`${baseUrl}/users`);
  return data.users ?? [];
}

export async function fetchAuditLog(baseUrl = "", room?: string): Promise<{ entries: unknown[]; total?: number }> {
  const qs = room ? `?room=${encodeURIComponent(room)}` : "";
  return getJSON(`${baseUrl}/audit${qs}`);
}

export async function fetchState<TWorldState = Record<string, unknown>>(
  baseUrl = "",
  room?: string,
): Promise<Partial<TWorldState>> {
  const qs = room ? `?room=${encodeURIComponent(room)}` : "";
  return getJSON(`${baseUrl}/state${qs}`);
}

export async function fetchAgents(baseUrl = "", room?: string): Promise<unknown[]> {
  const qs = room ? `?room=${encodeURIComponent(room)}` : "";
  const data = await getJSON<{ agents: unknown[] }>(`${baseUrl}/agents${qs}`);
  return data.agents ?? [];
}

export async function fetchRecordings(baseUrl = ""): Promise<RecordingInfo[]> {
  const data = await getJSON<{ recordings: RecordingInfo[] }>(`${baseUrl}/recordings`);
  return data.recordings ?? [];
}

export async function fetchRecording(filename: string, baseUrl = ""): Promise<string> {
  const res = await fetch(`${baseUrl}/recordings/${encodeURIComponent(filename)}`);
  return res.text();
}
