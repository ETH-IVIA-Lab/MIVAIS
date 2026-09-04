import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiPost, apiUpload } from "../../lib/api";
import type { AvailableStudy } from "../types";

export function NewStudyPage() {
  const navigate = useNavigate();
  const [available, setAvailable] = useState<AvailableStudy[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDir, setUploadDir] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);

  async function load() {
    const res = await apiGet<{ available: AvailableStudy[] }>("/api/admin/studies/new");
    setAvailable(res.available);
  }

  useEffect(() => {
    load();
  }, []);

  async function onRegister(dirName: string) {
    setBusy(dirName);
    setError(null);
    try {
      const res = await apiPost<{ ok?: boolean; error?: string; slug?: string }>("/api/admin/studies/register", {
        dir_name: dirName,
      });
      if (res.error) {
        setError(res.error);
        return;
      }
      navigate(`/studies/${res.slug}`);
    } finally {
      setBusy(null);
    }
  }

  async function onReload(slug: string) {
    setBusy(slug);
    setError(null);
    try {
      await apiPost(`/api/admin/studies/${slug}/reload`);
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function onUpload() {
    if (!uploadFile) return;
    setBusy("__upload__");
    setError(null);
    try {
      const form = new FormData();
      form.append("file", uploadFile);
      if (uploadDir.trim()) form.append("dir_name", uploadDir.trim());
      const res = await apiUpload<{ slug: string }>("/api/admin/studies/register-upload", form);
      navigate(`/studies/${res.slug}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await load();
    } finally {
      setBusy(null);
    }
  }

  if (!available) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="page-head">
        <h1>Register a study</h1>
      </div>
      {error && <div className="alert error">{error}</div>}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Upload a study.yaml</h2>
        <p className="muted small">
          Upload the study definition; it is validated against the schema and registered in one step.
          The individual tasks are still read from the study directory's <code>tasks/</code> folder on
          disk — if a referenced task file is missing, you get a precise error naming it.
        </p>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <input
            ref={fileInput}
            type="file"
            accept=".yaml,.yml"
            onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
          />
          <input
            type="text"
            placeholder="directory (defaults to the id: in the file)"
            value={uploadDir}
            onChange={(e) => setUploadDir(e.target.value)}
            style={{ minWidth: 280 }}
          />
          <button
            type="button"
            className="btn primary"
            disabled={!uploadFile || busy === "__upload__"}
            onClick={onUpload}
          >
            {busy === "__upload__" ? "Registering…" : "Upload & register"}
          </button>
        </div>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Or register a directory on disk</h2>
        <p className="muted small">
          Studies live as directories under <code>studies/</code>, each containing a <code>study.yaml</code> and a{" "}
          <code>tasks/</code> folder. Drop a study directory in place, refresh this page, and register it.
        </p>
        <table className="data">
          <thead>
            <tr>
              <th>Directory</th>
              <th>Slug</th>
              <th>Name</th>
              <th>Mode</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {available.map((a) => (
              <tr key={a.dir_name}>
                <td className="mono small">{a.dir_name}</td>
                <td className="mono small">{a.slug ?? "—"}</td>
                <td>{a.name ?? "—"}</td>
                <td>{a.mode ?? "—"}</td>
                <td>
                  {a.status === "error" && (
                    <span className="chip error" title={a.error ?? undefined}>
                      error
                    </span>
                  )}
                  {a.status === "not_registered" && <span className="chip">not registered</span>}
                  {a.status === "in_sync" && a.slug && (
                    <Link to={`/studies/${a.slug}`} className="chip ok">
                      in sync
                    </Link>
                  )}
                  {a.status === "out_of_sync" && a.slug && (
                    <Link to={`/studies/${a.slug}`} className="chip warn">
                      out of sync
                    </Link>
                  )}
                </td>
                <td>
                  {a.status === "not_registered" && (
                    <button type="button" className="btn primary" disabled={busy === a.dir_name} onClick={() => onRegister(a.dir_name)}>
                      Register
                    </button>
                  )}
                  {a.status === "out_of_sync" && a.slug && (
                    <button type="button" className="btn ghost" disabled={busy === a.slug} onClick={() => onReload(a.slug!)}>
                      Reload
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {available.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No study directories found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
