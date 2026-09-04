import { useEffect, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Link } from "react-router-dom";
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from "../../lib/api";
import { WEBHOOK_EVENTS, type WebhookOut, type WebhooksIndexResponse } from "../types";

export function WebhooksPage() {
  const [data, setData] = useState<WebhooksIndexResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // form state
  const [studySlug, setStudySlug] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<"studio" | "discord">("studio");
  const [events, setEvents] = useState<string[]>(["session_completed"]);
  const [description, setDescription] = useState("");

  async function load() {
    const res = await apiGet<WebhooksIndexResponse>("/api/admin/webhooks");
    setData(res);
    if (!res.all_studies.find((s) => s.slug === studySlug)) {
      setStudySlug(res.all_studies[0]?.slug ?? "");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggleEvent(ev: string) {
    setEvents((prev) => (prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev]));
  }

  async function onCreate() {
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/webhooks", {
        study_slug: studySlug,
        url: url.trim(),
        kind,
        events,
        description: description.trim(),
      });
      setUrl("");
      setDescription("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onToggle(hook: WebhookOut) {
    setError(null);
    try {
      await apiPatch(`/api/admin/webhooks/${hook.id}`, { active: !hook.active });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    }
  }

  const [confirmHook, setConfirmHook] = useState<WebhookOut | null>(null);

  async function onDelete(hook: WebhookOut) {
    setConfirmHook(null);
    setError(null);
    try {
      await apiDelete(`/api/admin/webhooks/${hook.id}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    }
  }

  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <ConfirmDialog
        open={confirmHook !== null}
        title="Delete this webhook?"
        body={<>Studio stops delivering events to <code>{confirmHook?.url}</code>.</>}
        confirmLabel="Delete webhook"
        onConfirm={() => confirmHook && onDelete(confirmHook)}
        onCancel={() => setConfirmHook(null)}
      />

      <div className="page-head">
        <div>
          <h1>Webhooks</h1>
          <p className="muted small" style={{ marginTop: 4 }}>
            Studio fires HTTP POSTs to your endpoints when configured events happen. Studio-type deliveries are
            signed with an HMAC-SHA256 header — verify it before trusting. Discord-type deliveries post a
            ready-made channel message.
          </p>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Add a webhook</h2>
        <div className="form-card" style={{ maxWidth: 620 }}>
          <label className="field">
            Study
            <select value={studySlug} onChange={(e) => setStudySlug(e.target.value)}>
              {data.all_studies.map((s) => (
                <option key={s.id} value={s.slug}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            URL
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/hooks/mivais — or a Discord webhook URL"
            />
          </label>
          <label className="field">
            Type
            <select value={kind} onChange={(e) => setKind(e.target.value as "studio" | "discord")}>
              <option value="studio">Studio JSON (signed)</option>
              <option value="discord">Discord</option>
            </select>
            <span className="muted small">
              Discord → in your server: Edit channel → Integrations → Webhooks → New Webhook → Copy URL. Best
              with the <code>participant_finished</code> event.
            </span>
          </label>
          <div className="field">
            Events
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
              {WEBHOOK_EVENTS.map((ev) => (
                <label key={ev} style={{ display: "flex", gap: 5, alignItems: "center", fontSize: 13 }}>
                  <input type="checkbox" checked={events.includes(ev)} onChange={() => toggleEvent(ev)} />
                  <code>{ev}</code>
                </label>
              ))}
            </div>
          </div>
          <label className="field">
            Description (optional)
            <input type="text" maxLength={120} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <div>
            <button
              type="button"
              className="btn primary"
              disabled={busy || !url.trim() || !studySlug || events.length === 0}
              onClick={onCreate}
            >
              Add webhook
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Registered webhooks</h2>
        {data.rows.length === 0 ? (
          <p className="muted">No webhooks registered yet.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Study</th>
                <th>URL</th>
                <th>Events</th>
                <th>Status</th>
                <th>Last delivery</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.rows.map(({ hook, study }) => (
                <tr key={hook.id}>
                  <td>{study ? <Link to={`/studies/${study.slug}`}>{study.name}</Link> : <span className="muted">—</span>}</td>
                  <td>
                    {hook.kind === "discord" && <span className="chip accent">discord</span>}{" "}
                    <code className="small">{hook.url.length > 56 ? hook.url.slice(0, 56) + "…" : hook.url}</code>
                    {hook.description && <div className="muted small">{hook.description}</div>}
                  </td>
                  <td>
                    {hook.events.map((e) => (
                      <span key={e} className="chip" style={{ marginRight: 4 }}>
                        {e}
                      </span>
                    ))}
                  </td>
                  <td>{hook.active ? <span className="chip ok">active</span> : <span className="chip">paused</span>}</td>
                  <td className="muted small">
                    {hook.last_delivery_at ? (
                      <>
                        {new Date(hook.last_delivery_at).toLocaleString()}
                        <br />
                        HTTP {hook.last_delivery_status ?? "—"} · {hook.delivery_count} delivered /{" "}
                        {hook.failure_count} failed
                      </>
                    ) : (
                      <span className="muted">no deliveries yet</span>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button type="button" className="btn ghost" onClick={() => onToggle(hook)}>
                      {hook.active ? "Pause" : "Resume"}
                    </button>{" "}
                    <button type="button" className="btn danger" onClick={() => setConfirmHook(hook)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
