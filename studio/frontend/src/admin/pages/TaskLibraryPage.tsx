import { useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPut, ApiError } from "../../lib/api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TrashIcon } from "../components/icons";
import { YamlEditor } from "../components/YamlEditor";

interface LibraryTaskRow {
  file: string;
  dir: string | null; 
  task_id: string | null;
  type: string | null;
  used_by: string[];
  read_only: boolean; 
}

const NEW_TASK_TEMPLATE = `# A library task: any study can reference it from a block via
#   - $ref: ../_lib/tasks/<this-file>
# The id must be unique within each study that uses it.
id: my-task
type: free_text
prompt_md: |
  ## Your question here
min_chars: 10
rows: 4
`;


export function TasksLibraryPane() {
  const [tasks, setTasks] = useState<LibraryTaskRow[]>([]);
  const [active, setActive] = useState<LibraryTaskRow | null>(null);
  const [draft, setDraft] = useState("");
  const [usedBy, setUsedBy] = useState<string[]>([]);
  const [isNew, setIsNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function load() {
    const t = await apiGet<{ tasks: LibraryTaskRow[] }>("/api/admin/library/tasks");
    setTasks(t.tasks);
  }

  useEffect(() => {
    load();
  }, []);

  function clearFlash() {
    setMessage(null);
    setWarning(null);
    setError(null);
  }

  async function select(row: LibraryTaskRow) {
    clearFlash();
    setIsNew(false);
    try {
      if (row.dir) {
        const res = await apiGet<{ content: string }>(
          `/api/admin/library/studies/${encodeURIComponent(row.dir)}?path=${encodeURIComponent(row.file)}`,
        );
        setActive(row);
        setDraft(res.content);
        setUsedBy([]);
      } else {
        const res = await apiGet<{ content: string; used_by: string[] }>(
          `/api/admin/library/tasks/${encodeURIComponent(row.file)}`,
        );
        setActive(row);
        setDraft(res.content);
        setUsedBy(res.used_by);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  function startNew() {
    setActive(null);
    setIsNew(true);
    setNewName("");
    setDraft(NEW_TASK_TEMPLATE);
    setUsedBy([]);
    clearFlash();
  }

  async function saveShared(file: string, content: string) {
    setBusy(true);
    clearFlash();
    try {
      const res = await apiPut<{ message?: string }>(
        `/api/admin/library/tasks/${encodeURIComponent(file)}`,
        { content },
      );
      setMessage(res.message ?? "Saved");
      setIsNew(false);
      await load();
      setActive({ file, dir: null, task_id: null, type: null, used_by: [], read_only: false });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function saveStudyTask(row: LibraryTaskRow, content: string) {
    setBusy(true);
    clearFlash();
    try {
      const res = await apiPut<{ message?: string; warning?: string }>(
        `/api/admin/library/studies/${encodeURIComponent(row.dir!)}`,
        { content, path: row.file },
      );
      if (res.warning) setWarning(res.warning);
      else setMessage(res.message ?? "Saved");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    if (isNew) {
      const name = newName.trim().replace(/\.yaml$/, "");
      if (!name) {
        setError("Give the new task a filename first.");
        return;
      }
      await saveShared(`${name}.yaml`, draft);
    } else if (active?.dir) {
      await saveStudyTask(active, draft);
    } else if (active) {
      await saveShared(active.file, draft);
    }
  }

  const [confirmDel, setConfirmDel] = useState<LibraryTaskRow | null>(null);

  async function onDelete() {
    const row = confirmDel;
    if (!row) return;
    clearFlash();
    try {
      await apiDelete(`/api/admin/library/tasks/${encodeURIComponent(row.file)}`);
      if (active?.file === row.file && !active?.dir) {
        setActive(null);
        setDraft("");
      }
      setMessage(`Deleted ${row.file}`);
      setConfirmDel(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setConfirmDel(null);
    }
  }

  const [confirmOverwrite, setConfirmOverwrite] = useState<{ name: string; content: string } | null>(null);

  async function onUpload(f: File) {
    const name = f.name.toLowerCase().endsWith(".yaml") ? f.name : `${f.name}.yaml`;
    const content = await f.text();
    const existing = tasks.find((t) => !t.dir && t.file === name);
    if (existing) {
      setConfirmOverwrite({ name, content });
      return;
    }
    await saveShared(name, content);
  }

  const refSnippet = active && !active.dir ? `- $ref: ../_lib/tasks/${active.file}` : null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <p className="muted small" style={{ margin: 0 }}>
          Every task on disk — the <strong>shared</strong> pool (<code>studies/_lib/tasks/</code>, referenced
          via <code>$ref</code>) and each study&apos;s own task files — one list, all editable. Registered
          studies run from frozen copies, so edits here never change them.
        </p>
        <div className="head-actions" style={{ flexShrink: 0 }}>
          <button type="button" className="btn" onClick={() => fileInput.current?.click()}>
            Upload .yaml
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".yaml,.yml"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
              e.target.value = "";
            }}
          />
          <button type="button" className="btn primary" onClick={startNew}>
            + New shared task
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmOverwrite !== null}
        title="Overwrite this task?"
        body={
          <>
            <code>{confirmOverwrite?.name}</code> already exists in the shared pool — its contents
            will be replaced by the uploaded file.
          </>
        }
        confirmLabel="Overwrite"
        danger={false}
        onConfirm={() => {
          const o = confirmOverwrite;
          setConfirmOverwrite(null);
          if (o) saveShared(o.name, o.content);
        }}
        onCancel={() => setConfirmOverwrite(null)}
      />

      <ConfirmDialog
        open={confirmDel !== null}
        title="Delete this task?"
        body={
          <>
            <code>{confirmDel?.file}</code> is removed from the shared pool. Studies already in use
            keep their frozen copy, but library studies referencing it will no longer load.
          </>
        }
        confirmLabel="Delete task"
        onConfirm={onDelete}
        onCancel={() => setConfirmDel(null)}
      />

      {error && <div className="alert error">{error}</div>}
      {warning && <div className="alert">{warning}</div>}
      {message && <div className="alert success">{message}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(300px, 420px) 1fr", gap: 16, alignItems: "start" }}>
        <div className="card compact" style={{ padding: 8 }}>
          {tasks.map((t) => (
            <div
              key={`${t.dir ?? "_lib"}/${t.file}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 8px",
                borderRadius: 8,
                cursor: "pointer",
                background: active && active.file === t.file && active.dir === t.dir ? "var(--accent-bg)" : "transparent",
              }}
              onClick={() => select(t)}
            >
              <span className="mono small" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
                {t.file.replace(/^tasks\//, "")}
              </span>
              {t.type && <span className="chip">{t.type}</span>}
              {t.dir ? (
                <span className="chip" title={`Belongs to study '${t.dir}'`}>
                  {t.dir}
                </span>
              ) : (
                <span className="chip ok" title="Shared pool — any study can $ref it">
                  shared
                </span>
              )}
              {!t.dir &&
                (t.read_only ? (
                  <span
                    className="chip warn"
                    title={`Referenced by legacy registration(s): ${t.used_by.join(", ")} — deletion blocked, editing allowed`}
                  >
                    refs {t.used_by.length}
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn icon-danger"
                    aria-label="Delete task"
                    title="Delete from the shared pool"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDel(t);
                    }}
                  >
                    <TrashIcon size={14} />
                  </button>
                ))}
            </div>
          ))}
          {tasks.length === 0 && (
            <p className="muted small" style={{ padding: 8 }}>
              No tasks yet. Create or upload one.
            </p>
          )}
        </div>

        <div>
          {isNew && (
            <div className="card compact" style={{ marginBottom: 10, display: "flex", gap: 8, alignItems: "center" }}>
              <label className="small" htmlFor="new-task-name">
                Filename:
              </label>
              <input
                id="new-task-name"
                placeholder="my-task"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                style={{ flex: 1 }}
              />
              <span className="mono small muted">.yaml</span>
            </div>
          )}
          {active || isNew ? (
            <>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <YamlEditor value={draft} onChange={setDraft} />
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
                <button type="button" className="btn primary" disabled={busy} onClick={onSave}>
                  {isNew ? "Create" : "Save"}
                </button>
                {usedBy.length > 0 && (
                  <span className="muted small">referenced by: {usedBy.join(", ")}</span>
                )}
                {refSnippet && (
                  <code
                    className="small"
                    style={{ marginLeft: "auto", cursor: "copy" }}
                    title="Click to copy — paste into any study's block task list"
                    onClick={() => navigator.clipboard?.writeText(refSnippet)}
                  >
                    {refSnippet}
                  </code>
                )}
              </div>
            </>
          ) : (
            <div className="empty">
              <p>Select a task on the left, or create/upload a new one.</p>
              <p className="muted small">
                Shared tasks are reused across studies via{" "}
                <code>- $ref: ../_lib/tasks/&lt;file&gt;.yaml</code> (inline overrides shallow-merge on
                top); study tasks are referenced by bare id inside their own study.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
