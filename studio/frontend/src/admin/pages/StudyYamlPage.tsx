import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiPost, apiUpload, ApiError } from "../../lib/api";
import type { Study } from "../../lib/types";
import { YamlEditor } from "../components/YamlEditor";

interface YamlFile {
  path: string;
  content: string;
}

const VIDEO_ACCEPT = "video/mp4,video/webm,video/quicktime,video/ogg";


function withVideoUrl(content: string, url: string): string {
  const line = `video_url: "${url}"`;
  if (/^video_url:.*$/m.test(content)) return content.replace(/^video_url:.*$/m, line);
  return content.replace(/\n+$/, "") + "\n" + line + "\n";
}

export function StudyYamlPage() {
  const { slug = "" } = useParams();
  const [study, setStudy] = useState<Study | null>(null);
  const [files, setFiles] = useState<YamlFile[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const videoInputRef = useRef<HTMLInputElement>(null);

  async function load() {
    const res = await apiGet<{ study: Study; files: YamlFile[] }>(`/api/admin/studies/${slug}/yaml`);
    setStudy(res.study);
    setFiles(res.files);
    if (!activePath && res.files.length) {
      setActivePath(res.files[0].path);
      setDraft(res.files[0].content);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  function selectFile(path: string) {
    const f = files.find((x) => x.path === path);
    if (!f) return;
    setActivePath(path);
    setDraft(f.content);
    setMessage(null);
    setError(null);
  }

  async function onSave() {
    if (!activePath) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await apiPost<{ ok?: boolean; error?: string; message?: string; warning?: string }>(
        `/api/admin/studies/${slug}/yaml`,
        { relative_path: activePath, content: draft },
      );
      if (res.error) setError(res.error);
      else setMessage(res.warning ?? res.message ?? "Saved");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function onUploadVideo(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !activePath) return;
    setUploading(true);
    setError(null);
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiUpload<{ url: string; filename: string }>(`/api/admin/studies/${slug}/upload-video`, form);
      setDraft((d) => withVideoUrl(d, res.url));
      setMessage(`Uploaded "${res.filename}" — set video_url in "${activePath}". Click Save to apply it.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Video upload failed.");
    } finally {
      setUploading(false);
    }
  }

  if (!study) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            <Link to={`/studies/${slug}`}>{study.name}</Link> / YAML
          </div>
          <h1>Study YAML</h1>
        </div>
        <div className="head-actions">
          <button
            type="button"
            className="btn ghost"
            disabled={uploading || !activePath}
            title="Upload a video and set video_url on the currently open task file"
            onClick={() => videoInputRef.current?.click()}
          >
            {uploading ? "Uploading…" : "Upload video"}
          </button>
          <input ref={videoInputRef} type="file" accept={VIDEO_ACCEPT} style={{ display: "none" }} onChange={onUploadVideo} />
          <button type="button" className="btn primary" disabled={busy || !activePath} onClick={onSave}>
            Save
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16 }}>
        <div className="card compact" style={{ padding: 8 }}>
          {files.map((f) => (
            <button
              key={f.path}
              type="button"
              className="nav-item"
              style={{
                width: "100%",
                border: 0,
                cursor: "pointer",
                font: "inherit",
                background: f.path === activePath ? "var(--accent-bg)" : "transparent",
              }}
              onClick={() => selectFile(f.path)}
            >
              <span className="mono small">{f.path}</span>
            </button>
          ))}
        </div>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {activePath && <YamlEditor value={draft} onChange={setDraft} />}
        </div>
      </div>
    </div>
  );
}
