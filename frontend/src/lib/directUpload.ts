import { genericErrorMessage, parseDetail } from "@/lib/api";

// Sends a file in parts straight into the bucket, every request stays small enough for any proxy.
// One core for every tool and the AI assistant: start, signed part URLs, parts, complete.

const BASE = "/api/uploads";
const URL_BATCH = 10;
const MAX_TRIES = 8;

interface Session {
  direct: boolean;
  token: string;
  part_size: number;
  part_count: number;
  uploaded: number[];
  done?: boolean;
}

type HttpError = Error & { status?: number };

export interface UploadOptions {
  tool: string;
  file: File;
  onPercent?: (percent: number) => void;
  // Shown when the server gives no reason, the locale's generic error text by default.
  failedText?: string;
  signal?: AbortSignal;
  // Extra facts the tool's rule checks, for example the workspace of the AI assistant.
  context?: Record<string, string>;
}

function storageKey(tool: string, file: File, context?: Record<string, string>): string {
  const where = context ? JSON.stringify(context) : "";
  return `askf-upload:${tool}:${where}:${file.name}:${file.size}:${file.lastModified}`;
}

function readToken(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function writeToken(key: string, token: string | null): void {
  try {
    if (token) localStorage.setItem(key, token);
    else localStorage.removeItem(key);
  } catch { /* the upload works without resuming too */ }
}

async function httpError(res: Response, fallback: string): Promise<HttpError> {
  const body = await res.json().catch(() => null);
  // The reason arrives sometimes as an object and sometimes as text.
  return Object.assign(new Error(parseDetail(body?.detail, fallback)), { status: res.status });
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// Waits until the device is online again, a dropped line should not cost the upload.
function whenOnline(): Promise<void> {
  if (typeof navigator === "undefined" || navigator.onLine) return Promise.resolve();
  return new Promise((r) => window.addEventListener("online", () => r(), { once: true }));
}

// Without cookies the browser opens a connection of its own, the page's requests never queue behind a part.
async function putPart(url: string, blob: Blob, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, { method: "PUT", body: blob, credentials: "omit", signal });
  } catch {
    throw Object.assign(new Error("network"), { status: 0 });
  }
  if (!res.ok) throw Object.assign(new Error(`part ${res.status}`), { status: res.status });
}

function postJson(url: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  return fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

/** Forgets the saved token of a file, call it once the tool took the upload or refused it for good. */
export function forgetUpload(tool: string, file: File, context?: Record<string, string>): void {
  writeToken(storageKey(tool, file, context), null);
}

/**
 * Uploads the file in parts, joins it on the server and returns the token the tool takes it by.
 * Null means there is no bucket, the file then goes whole with the tool's own request.
 */
export async function uploadFile(opts: UploadOptions): Promise<string | null> {
  const { tool, file, signal, context } = opts;
  const failedText = opts.failedText ?? genericErrorMessage();
  const onPercent = opts.onPercent ?? (() => {});
  const key = storageKey(tool, file, context);

  let session: Session | null = null;
  const saved = readToken(key);
  if (saved) {
    const res = await fetch(`${BASE}/${saved}`, { credentials: "include", signal });
    if (res.ok) session = await res.json();
    else writeToken(key, null);
  }
  if (!session) {
    const res = await postJson(BASE, { tool, filename: file.name, size: file.size, context: context ?? {} }, signal);
    if (!res.ok) throw await httpError(res, failedText);
    session = await res.json();
    if (!session?.direct) return null;
    writeToken(key, session.token);
  }

  const { token, part_size: partSize, part_count: partCount } = session;
  if (!session.done) {
    const done = new Set(session.uploaded);
    const partBytes = (n: number) => Math.min(partSize, file.size - (n - 1) * partSize);
    let doneBytes = [...done].reduce((sum, n) => sum + partBytes(n), 0);
    const report = () => onPercent(Math.min(99, Math.floor((doneBytes / Math.max(1, file.size)) * 100)));
    report();

    const todo = Array.from({ length: partCount }, (_, i) => i + 1).filter((n) => !done.has(n));
    let anyPartSent = done.size > 0;
    // One part at a time, the line stays usable for the page and nothing runs in parallel.
    for (let i = 0; i < todo.length; i += URL_BATCH) {
      const batch = todo.slice(i, i + URL_BATCH);
      const urlRes = await postJson(`${BASE}/${token}/urls`, { parts: batch }, signal);
      if (!urlRes.ok) throw await httpError(urlRes, failedText);
      const { urls } = (await urlRes.json()) as { urls: Record<string, string> };

      for (const n of batch) {
        const blob = file.slice((n - 1) * partSize, (n - 1) * partSize + partBytes(n));
        for (let attempt = 1; ; attempt++) {
          try {
            await whenOnline();
            await putPart(urls[String(n)], blob, signal);
            break;
          } catch (err) {
            if (signal?.aborted) throw err;
            const status = (err as HttpError).status ?? 0;
            // The bucket refuses the browser outright, the classic route still works then.
            if (!anyPartSent && status === 0 && attempt === 1) {
              await fetch(`${BASE}/${token}`, { method: "DELETE", credentials: "include" }).catch(() => {});
              writeToken(key, null);
              return null;
            }
            if (attempt >= MAX_TRIES) throw Object.assign(new Error(failedText), { status });
            await sleep(Math.min(30_000, 1000 * 2 ** (attempt - 1)));
          }
        }
        anyPartSent = true;
        doneBytes += partBytes(n);
        report();
      }
    }
  }

  const res = await postJson(`${BASE}/${token}/complete`, {}, signal);
  if (!res.ok) {
    // Parts that never arrived are sent again on the next try, everything else starts over.
    if (res.status !== 409) writeToken(key, null);
    throw await httpError(res, failedText);
  }
  onPercent(100);
  return token;
}

/**
 * Puts one file on a form for a tool route: as the token of a direct upload when possible,
 * otherwise as the file itself. Returns a function that forgets the token once the route answered.
 */
export async function appendFile(
  formData: FormData,
  opts: UploadOptions & { field?: string },
): Promise<() => void> {
  const token = await uploadFile(opts);
  if (token) formData.append("upload_token", token);
  else formData.append(opts.field ?? "file", opts.file);
  return () => forgetUpload(opts.tool, opts.file, opts.context);
}

/**
 * Puts several files on a form: each as a token under upload_tokens when possible, otherwise
 * under the classic field. A tool's rule takes all of its file types, so in practice all go one way.
 */
export async function appendFiles(
  formData: FormData,
  opts: Omit<UploadOptions, "file" | "onPercent"> & {
    files: File[];
    field?: string;
    onPercent?: (fileIndex: number, percent: number) => void;
  },
): Promise<() => void> {
  const sent: File[] = [];
  for (let i = 0; i < opts.files.length; i++) {
    const file = opts.files[i];
    const token = await uploadFile({ ...opts, file, onPercent: (p) => opts.onPercent?.(i, p) });
    if (token) formData.append("upload_tokens", token);
    else formData.append(opts.field ?? "files", file);
    sent.push(file);
  }
  return () => sent.forEach((file) => forgetUpload(opts.tool, file, opts.context));
}
