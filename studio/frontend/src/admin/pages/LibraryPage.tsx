import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiGet, apiPost, apiPut, apiUpload, ApiError } from "../../lib/api";
import { YamlEditor } from "../components/YamlEditor";
import { TasksLibraryPane } from "./TaskLibraryPage";

const VIDEO_ACCEPT = "video/mp4,video/webm,video/quicktime,video/ogg";


function withVideoUrl(content: string, url: string): string {
  const line = `video_url: "${url}"`;
  if (/^video_url:.*$/m.test(content)) return content.replace(/^video_url:.*$/m, line);
  return content.replace(/\n+$/, "") + "\n" + line + "\n";
}

export function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "tasks" ? "tasks" : "studies";

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Library</h1>
        </div>
        <div className="head-actions" role="tablist" aria-label="Library section">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "tasks"}
            className={`btn ${tab === "tasks" ? "primary" : "ghost"}`}
            onClick={() => setParams({ tab: "tasks" }, { replace: true })}
          >
            Tasks
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "studies"}
            className={`btn ${tab === "studies" ? "primary" : "ghost"}`}
            onClick={() => setParams({ tab: "studies" }, { replace: true })}
          >
            Studies
          </button>
        </div>
      </div>
      {tab === "tasks" ? <TasksLibraryPane /> : <StudiesLibraryPane />}
    </div>
  );
}

// ── Studies tab ───────────────────────────────────────────────────────────

interface LibraryStudyRow {
  dir: string;
  study_id: string | null;
  name: string | null;
  mode: string | null;
  in_use: string[];
}

interface InUseRow {
  slug: string;
  name: string | null;
  mode: string | null;
  registered: boolean;
  archived: boolean;
}

interface StudyFileResponse {
  dir: string;
  path: string;
  files: string[];
  content: string;
  in_use: string[];
}

const NEW_STUDY_TEMPLATE = `# A minimal study. Edit, press Create, then "Use study" to freeze a copy and
# get join codes. Task files can live inline (tasks:) or under <dir>/tasks/
# and be referenced from blocks.
id: my-study
name: My Study
mode: singleplayer
consent_text_md: |
  # Consent
  By continuing you agree to take part in this study.
tasks:
  - id: welcome
    type: info_screen
    prompt_md: |
      ## Welcome
      Thanks for taking part!
`;

const NEW_TASK_FILE_TEMPLATE = `# A task in this study's tasks/ folder. Reference it from a block by its id,
# which defaults to this filename (without .yaml).
type: free_text
prompt_md: |
  ## Your question here
min_chars: 10
rows: 4
`;

function StudiesLibraryPane() {
  const [studies, setStudies] = useState<LibraryStudyRow[]>([]);
  const [inUse, setInUse] = useState<InUseRow[]>([]);
  // active selection: a library dir OR a frozen in-use copy (read-only).
  const [active, setActive] = useState<string | null>(null);
  const [activeFrozen, setActiveFrozen] = useState(false);
  const [activePath, setActivePath] = useState("study.yaml");
  const [files, setFiles] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [activeInUse, setActiveInUse] = useState<string[]>([]);
  const [isNew, setIsNew] = useState(false);
  const [newDir, setNewDir] = useState("");
  const [isNewFile, setIsNewFile] = useState(false);
  const [newFileName, setNewFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadingVideo, setUploadingVideo] = useState(false);
  const videoInputRef = useRef<HTMLInputElement>(null);

  async function load() {
    const [s, u] = await Promise.all([
      apiGet<{ studies: LibraryStudyRow[] }>("/api/admin/library/studies"),
      apiGet<{ studies: InUseRow[] }>("/api/admin/library/inuse"),
    ]);
    setStudies(s.studies);
    setInUse(u.studies);
  }

  useEffect(() => {
    load();
  }, []);

  function clearFlash() {
    setMessage(null);
    setWarning(null);
    setError(null);
  }

  async function select(dir: string, path = "study.yaml", frozen = false) {
    clearFlash();
    setIsNew(false);
    setIsNewFile(false);
    try {
      const base = frozen ? "/api/admin/library/inuse" : "/api/admin/library/studies";
      const res = await apiGet<StudyFileResponse>(
        `${base}/${encodeURIComponent(dir)}?path=${encodeURIComponent(path)}`,
      );
      setActive(dir);
      setActiveFrozen(frozen);
      setActivePath(res.path);
      setFiles(res.files);
      setDraft(res.content);
      setActiveInUse(res.in_use);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  function startNew() {
    setActive(null);
    setActiveFrozen(false);
    setIsNew(true);
    setIsNewFile(false);
    setNewDir("");
    setFiles([]);
    setActivePath("study.yaml");
    setDraft(NEW_STUDY_TEMPLATE);
    setActiveInUse([]);
    clearFlash();
  }

  function startNewFile() {
    if (!active || activeFrozen) return;
    setIsNewFile(true);
    setNewFileName("");
    setDraft(NEW_TASK_FILE_TEMPLATE);
    clearFlash();
  }

  async function saveAs(dir: string, content: string, path = "study.yaml") {
    setBusy(true);
    clearFlash();
    try {
      const res = await apiPut<{ message?: string; warning?: string }>(
        `/api/admin/library/studies/${encodeURIComponent(dir)}`,
        { content, path },
      );
      setIsNew(false);
      setIsNewFile(false);
      await load();
      // select() clears flash messages, so surface the result afterwards.
      await select(dir, path);
      if (res.warning) setWarning(res.warning);
      else setMessage(res.message ?? "Saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    if (isNew) {
      const dir = newDir.trim();
      if (!dir) {
        setError("Give the new study a directory name first (e.g. my-study).");
        return;
      }
      await saveAs(dir, draft);
    } else if (isNewFile && active) {
      const name = newFileName.trim().replace(/\.yaml$/, "");
      if (!name) {
        setError("Give the new task file a name first (e.g. my-question).");
        return;
      }
      await saveAs(active, draft, `tasks/${name}.yaml`);
    } else if (active && !activeFrozen) {
      await saveAs(active, draft, activePath);
    }
  }

  async function onUploadVideo(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !active || activeFrozen) return;
    setUploadingVideo(true);
    clearFlash();
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiUpload<{ url: string; filename: string }>(
        `/api/admin/library/studies/${encodeURIComponent(active)}/upload-video`,
        form,
      );
      setDraft((d) => withVideoUrl(d, res.url));
      setMessage(`Uploaded "${res.filename}" — set video_url in "${activePath}". Click Save to apply it.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Video upload failed.");
    } finally {
      setUploadingVideo(false);
    }
  }

  async function onUse(dir: string) {
    setBusy(true);
    clearFlash();
    try {
      const res = await apiPost<{ slug: string; code: string }>("/api/admin/studies/register", {
        dir_name: dir,
      });
      setMessage(
        `Froze a copy as '${res.slug}' — it is now in use (read-only). First join code: ${res.code}`,
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <p className="muted small" style={{ margin: 0 }}>
          The library is always editable. <strong>Use study</strong> freezes a self-contained copy
          (study.yaml + every referenced task) into <em>In use</em> — read-only, one per version — and
          registers it for participants. Edits here never change a frozen copy.
        </p>
        <div className="head-actions" style={{ flexShrink: 0 }}>
          <button type="button" className="btn primary" onClick={startNew}>
            + New study
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {warning && <div className="alert">{warning}</div>}
      {message && <div className="alert success">{message}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(300px, 380px) 1fr", gap: 16, alignItems: "start" }}>
        <div>
          <div className="card compact" style={{ padding: 8 }}>
            {studies.map((s) => (
              <div
                key={s.dir}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 8px",
                  borderRadius: 8,
                  cursor: "pointer",
                  background: s.dir === active && !activeFrozen ? "var(--accent-bg)" : "transparent",
                }}
                onClick={() => select(s.dir)}
              >
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span className="mono small" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.dir}/
                  </span>
                  {s.name && (
                    <span className="muted small" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {s.name}
                    </span>
                  )}
                </span>
                {s.mode === "multiplayer" && <span className="chip">multi</span>}
                {s.in_use.length > 0 && (
                  <span className="chip ok" title={`Frozen copies: ${s.in_use.join(", ")}`}>
                    in use ×{s.in_use.length}
                  </span>
                )}
              </div>
            ))}
            {studies.length === 0 && (
              <p className="muted small" style={{ padding: 8 }}>
                No studies in the library yet. Create one.
              </p>
            )}
          </div>

          <div className="card compact" style={{ padding: 8, marginTop: 14 }}>
            <div className="muted small" style={{ padding: "2px 8px 6px", textTransform: "uppercase", letterSpacing: "0.05em", fontSize: "0.7rem" }}>
              In use — frozen copies (read-only)
            </div>
            {inUse.map((c) => (
              <div
                key={c.slug}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 8px",
                  borderRadius: 8,
                  cursor: "pointer",
                  background: c.slug === active && activeFrozen ? "var(--accent-bg)" : "transparent",
                }}
                onClick={() => select(c.slug, "study.yaml", true)}
              >
                <span className="mono small" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {c.slug}
                </span>
                {c.archived ? (
                  <span className="chip">archived</span>
                ) : c.registered ? (
                  <Link to={`/studies/${c.slug}`} className="chip ok" onClick={(e) => e.stopPropagation()}>
                    open →
                  </Link>
                ) : (
                  <span className="chip warn" title="Copy exists on disk but no registered study points at it">
                    orphaned
                  </span>
                )}
              </div>
            ))}
            {inUse.length === 0 && (
              <p className="muted small" style={{ padding: 8 }}>
                Nothing in use yet — select a study and press <strong>Use study</strong>.
              </p>
            )}
          </div>
        </div>

        <div>
          {isNew && (
            <div className="card compact" style={{ marginBottom: 10, display: "flex", gap: 8, alignItems: "center" }}>
              <label className="small" htmlFor="new-study-dir">
                Directory:
              </label>
              <input
                id="new-study-dir"
                placeholder="my-study"
                value={newDir}
                onChange={(e) => setNewDir(e.target.value)}
                style={{ flex: 1 }}
              />
              <span className="mono small muted">/study.yaml</span>
            </div>
          )}
          {active && !isNew && (
            <div
              className="card compact"
              style={{ marginBottom: 10, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}
            >
              {files.map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`btn ${!isNewFile && f === activePath ? "primary" : "ghost"}`}
                  style={{ padding: "2px 10px", fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}
                  onClick={() => select(active, f, activeFrozen)}
                >
                  {f}
                </button>
              ))}
              {!activeFrozen && (
                <button
                  type="button"
                  className="btn ghost"
                  style={{ padding: "2px 10px", fontSize: 12 }}
                  title="Add a task file to this study (reference it from a block by its id)"
                  onClick={startNewFile}
                >
                  + task file
                </button>
              )}
            </div>
          )}
          {isNewFile && active && (
            <div className="card compact" style={{ marginBottom: 10, display: "flex", gap: 8, alignItems: "center" }}>
              <span className="mono small muted">{active}/tasks/</span>
              <input
                placeholder="my-question"
                value={newFileName}
                onChange={(e) => setNewFileName(e.target.value)}
                style={{ flex: 1 }}
                autoFocus
              />
              <span className="mono small muted">.yaml</span>
            </div>
          )}
          {active || isNew ? (
            <>
              {activeFrozen && (
                <div className="alert" style={{ marginBottom: 10 }}>
                  Frozen in-use copy — read-only. Edit the study in the library and press{" "}
                  <strong>Use study</strong> to freeze a new version.
                </div>
              )}
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <YamlEditor value={draft} onChange={activeFrozen ? () => {} : setDraft} />
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
                {!activeFrozen && (
                  <button type="button" className="btn primary" disabled={busy} onClick={onSave}>
                    {isNew || isNewFile ? "Create" : "Save"}
                  </button>
                )}
                {active && !isNew && !isNewFile && !activeFrozen && (
                  <>
                    <button
                      type="button"
                      className="btn ghost"
                      disabled={uploadingVideo}
                      title="Upload a video and set video_url on the currently open task file"
                      onClick={() => videoInputRef.current?.click()}
                    >
                      {uploadingVideo ? "Uploading…" : "Upload video"}
                    </button>
                    <input ref={videoInputRef} type="file" accept={VIDEO_ACCEPT} style={{ display: "none" }} onChange={onUploadVideo} />
                  </>
                )}
                {active && !isNew && !activeFrozen && (
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    title="Freeze a self-contained copy into 'In use' and register it (repeat for a new version)"
                    onClick={() => onUse(active)}
                  >
                    Use study
                  </button>
                )}
                {activeFrozen && active && (
                  <Link to={`/studies/${active}`} className="btn ghost">
                    Open study →
                  </Link>
                )}
                {!activeFrozen && activeInUse.length > 0 && (
                  <span className="muted small" style={{ marginLeft: "auto" }}>
                    in use as: {activeInUse.join(", ")}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="empty">
              <p>Select a study on the left, or create a new one.</p>
              <p className="muted small">
                Everything in the library stays editable — <strong>Use study</strong> snapshots the
                study and all of its tasks into a read-only in-use copy, so running studies are never
                affected by later edits. Shared cross-study tasks live in the <strong>Tasks</strong> tab.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
