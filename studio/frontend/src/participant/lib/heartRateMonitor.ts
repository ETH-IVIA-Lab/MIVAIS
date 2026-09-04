/** Participant-side BLE heart-rate capture. 
 *
 * Uses the standard BLE Heart Rate Service (0x180D) / Heart Rate Measurement
 * characteristic (0x2A37) — what chest straps and fitness trackers broadcast
 * generically, so no vendor-specific integration is needed.
 */

export type HRStatus = "idle" | "connecting" | "connected" | "disconnected" | "denied" | "unsupported" | "error";

interface HRSampleOut {
  t_wall: string;
  bpm: number;
}

interface QueuedBatch {
  id?: number;
  seq: number;
  batch_started_wall: string;
  samples: HRSampleOut[];
}

const DB_NAME = "studio-biometric-queue";
const STORE = "chunks";
const FLUSH_MS = 5000;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function dbTx<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => Promise<T>): Promise<T> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    let out: T;
    tx.oncomplete = () => resolve(out);
    tx.onerror = () => reject(tx.error);
    Promise.resolve(fn(tx.objectStore(STORE))).then((v) => (out = v));
  });
}

const queuePush = (item: QueuedBatch) =>
  dbTx<number>("readwrite", (s) => new Promise((res) => {
    const r = s.add(item);
    r.onsuccess = () => res(r.result as number);
  }));
const queuePeek = (n = 8) =>
  dbTx<QueuedBatch[]>("readonly", (s) => new Promise((res) => {
    const out: QueuedBatch[] = [];
    const req = s.openCursor();
    req.onsuccess = (e) => {
      const cur = (e.target as IDBRequest<IDBCursorWithValue | null>).result;
      if (cur && out.length < n) {
        out.push(cur.value);
        cur.continue();
      } else res(out);
    };
  }));
const queueDel = (id: number) =>
  dbTx<boolean>("readwrite", (s) => new Promise((res) => {
    const r = s.delete(id);
    r.onsuccess = () => res(true);
  }));

async function rawUpload(seq: number, batchStartedWall: string, samples: HRSampleOut[]): Promise<void> {
  const r = await fetch("/ingest/biometric-chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seq, batch_started_wall: batchStartedWall, samples }),
  });
  if (!r.ok) throw new Error(`ingest-failed-${r.status}`);
}

/** Standard GATT Heart Rate Measurement layout: flags byte then either an
 * 8-bit or 16-bit bpm value (bit 0 of flags selects the width). Energy
 * expended / RR-interval fields, if present, always come after bpm */
function parseHeartRate(view: DataView): number {
  const flags = view.getUint8(0);
  return (flags & 0x1) !== 0 ? view.getUint16(1, true) : view.getUint8(1);
}

let status: HRStatus = "idle";
let bpm: number | null = null;
const listeners = new Set<(status: HRStatus, bpm: number | null) => void>();

function notify() {
  for (const cb of listeners) cb(status, bpm);
}

function setStatus(s: HRStatus) {
  status = s;
  notify();
}

let device: BluetoothDevice | null = null;
let buffer: HRSampleOut[] = [];
let seq = 0;
let flushTimer: number | undefined;
let draining = false;
let reconnecting = false;

async function drain(): Promise<void> {
  if (draining) return;
  draining = true;
  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const items = await queuePeek(8);
      if (!items.length) break;
      const item = items[0];
      try {
        await rawUpload(item.seq, item.batch_started_wall, item.samples);
        await queueDel(item.id!);
      } catch {
        break; // bail; try again next tick
      }
    }
  } catch {
    // ignore
  }
  draining = false;
}

function flush() {
  if (!buffer.length) return;
  const samples = buffer;
  buffer = [];
  const mySeq = seq;
  seq += 1;
  const batchStartedWall = samples[0].t_wall;
  rawUpload(mySeq, batchStartedWall, samples)
    .then(drain)
    .catch(() => queuePush({ seq: mySeq, batch_started_wall: batchStartedWall, samples }));
}

function onCharacteristicValueChanged(e: Event) {
  const char = e.target as BluetoothRemoteGATTCharacteristic;
  if (!char.value) return;
  const value = parseHeartRate(char.value);
  bpm = value;
  notify();
  buffer.push({ t_wall: new Date().toISOString(), bpm: value });
}

async function subscribeToDevice(bleDevice: BluetoothDevice): Promise<void> {
  const server = await bleDevice.gatt!.connect();
  const service = await server.getPrimaryService("heart_rate");
  const char = await service.getCharacteristic("heart_rate_measurement");
  char.addEventListener("characteristicvaluechanged", onCharacteristicValueChanged);
  await char.startNotifications();
}

function onGattDisconnected() {
  bpm = null;
  if (reconnecting || !device?.gatt) {
    setStatus("disconnected");
    return;
  }
  reconnecting = true;
  subscribeToDevice(device)
    .then(() => {
      reconnecting = false;
      setStatus("connected");
    })
    .catch(() => {
      reconnecting = false;
      setStatus("disconnected");
    });
}

export async function connect(): Promise<void> {
  if (!navigator.bluetooth) {
    setStatus("unsupported");
    throw new Error("bluetooth-unsupported");
  }
  setStatus("connecting");
  try {
    device = await navigator.bluetooth.requestDevice({ filters: [{ services: ["heart_rate"] }] });
    device.addEventListener("gattserverdisconnected", onGattDisconnected);
    await subscribeToDevice(device);
    setStatus("connected");
    if (flushTimer) window.clearInterval(flushTimer);
    flushTimer = window.setInterval(flush, FLUSH_MS);
    window.addEventListener("online", drain);
    drain(); // pick up anything queued from a previous page load
  } catch (err) {
    const name = (err as { name?: string })?.name;
    setStatus(name === "NotFoundError" || name === "SecurityError" ? "denied" : "error");
    throw err;
  }
}

export function getStatus(): { status: HRStatus; bpm: number | null } {
  return { status, bpm };
}

export function subscribe(cb: (status: HRStatus, bpm: number | null) => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
