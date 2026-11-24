const API_BASE = "";
const BACKEND_BASE = "/api";

/** The backend sends exactly this detail when a test access has run out. */
const ACCESS_EXPIRED_DETAIL = "access_expired";
/** The expired access lands on the login page, which says so and offers a fresh code. */
const EXPIRED_PATH = "/login?expired=1";
/** Pages that talk about the expiry themselves and must not be thrown around. */
const EXPIRY_HOME = ["/login", "/redeem", "/redeem/expired"];
/** Pages anyone may see, a stale session there is dropped instead of sending the visitor to the login. */
export const PUBLIC_PAGES = ["/", "/info", "/imprint", "/privacy", "/campusmap"];

/** The path without its locale prefix, /en/login is the same page as /login. */
function ohneSprache(path: string): string {
  return path.replace(/^\/en(?=\/|$)/, "") || "/";
}

function isPublicPage(path: string): boolean {
  return PUBLIC_PAGES.includes(ohneSprache(path));
}

// The first redirect wins, a 401 running behind it must not swallow the expiry hint.
let umgeleitet = false;

function verlassen(ziel: string) {
  if (umgeleitet) return;
  umgeleitet = true;
  window.location.href = ziel;
}

/** Clears the cookie the backend no longer knows and shows the same page again as a guest. */
function sitzungVerwerfen() {
  if (umgeleitet) return;
  umgeleitet = true;
  fetch("/auth/logout", { method: "POST", credentials: "include" })
    .catch(() => undefined)
    .finally(() => window.location.reload());
}

const FALLBACKS = {
  de: {
    limitReached: "Limit erreicht",
    unknownError: "Unbekannter Fehler",
    jobStatusError: "Fehler beim Abrufen des Job-Status",
    // Shown whenever the backend gives no usable detail - never the raw status code.
    genericError: "Da ist etwas schiefgelaufen. Bitte versuche es erneut oder wende dich an den Support, falls es weiter nicht klappt.",
    jobFailed: "Job fehlgeschlagen",
    downloadFailed: "Download fehlgeschlagen",
  },
  en: {
    limitReached: "Limit reached",
    unknownError: "Unknown error",
    jobStatusError: "Failed to load job status",
    genericError: "Something went wrong. Please try again, or contact support if it keeps happening.",
    jobFailed: "Job failed",
    downloadFailed: "Download failed",
  },
} as const;

function fallback(key: keyof typeof FALLBACKS["de"]): string {
  return FALLBACKS[readLocaleFromCookie()][key];
}

/** Locale-aware fallback text for spots outside ApiClient that need one, never the raw status code. */
export function genericErrorMessage(): string {
  return fallback("genericError");
}

class QuotaError extends Error {
  quota_type: string;
  label: string;
  reset_at: string | null;
  used: number;
  limit: number;

  constructor(detail: Record<string, unknown>) {
    super(typeof detail.message === "string" ? detail.message : fallback("limitReached"));
    this.name = "QuotaError";
    this.quota_type = String(detail.quota_type ?? "");
    this.label = String(detail.label ?? detail.quota_type ?? "");
    this.reset_at = (detail.reset_at as string | null) ?? null;
    this.used = Number(detail.used ?? 0);
    this.limit = Number(detail.limit ?? 0);
  }
}

export function parseDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in (detail as object)) {
    return String((detail as Record<string, unknown>).message);
  }
  return fallback;
}

// A plain name may carry a bare percent sign, which is no encoding at all.
function decodeName(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

// Takes the file name from the header, otherwise the fallback.
export function filenameFromDisposition(disposition: string | null, fallback: string): string {
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''(.+?)(?:;|$)/i);
    if (utf8Match) return decodeName(utf8Match[1].trim());
    const basicMatch = disposition.match(/filename="?([^";\n]+)"?/i);
    if (basicMatch) return decodeName(basicMatch[1].trim());
  }
  return fallback;
}

function _parseErrorResponse(errorBody: { detail?: unknown }, fallbackStatus: number): Error {
  const detail = errorBody.detail;
  if (detail && typeof detail === "object" && "quota_type" in (detail as object)) {
    return new QuotaError(detail as Record<string, unknown>);
  }
  // Blocks carry their sentence in detail.message, otherwise only 429 would show.
  if (detail && typeof detail === "object" && "message" in (detail as object)) {
    return new Error(String((detail as Record<string, unknown>).message));
  }
  if (typeof detail === "string") return new Error(detail);
  // Validation errors and bodies without a usable detail land here - log the status for debugging,
  // but never put the raw code in front of the user.
  console.error(`API error ${fallbackStatus}:`, detail);
  return new Error(fallback("genericError"));
}

/** Turns a failed response into the error the callers show. */
async function throwIfFailed(response: Response): Promise<void> {
  if (response.ok) return;
  const error = await response.json().catch(() => ({ detail: fallback("unknownError") }));
  throw _parseErrorResponse(error, response.status);
}

async function blobWithName(response: Response, fallbackName: string): Promise<{ blob: Blob; filename: string }> {
  const blob = await response.blob();
  return { blob, filename: filenameFromDisposition(response.headers.get("Content-Disposition"), fallbackName) };
}

function readLocaleFromCookie(): "de" | "en" {
  if (typeof document === "undefined") return "de";
  const match = document.cookie.match(/(?:^|;\s*)NEXT_LOCALE=(de|en)/);
  return (match?.[1] as "de" | "en") ?? "de";
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async fetch(path: string, options: RequestInit = {}): Promise<Response> {
    const headers = new Headers(options.headers);
    if (!headers.has("Accept-Language")) {
      headers.set("Accept-Language", readLocaleFromCookie());
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      credentials: "include",
      headers,
    });

    if (response.status === 401 && typeof window !== "undefined") {
      const currentPath = window.location.pathname;
      if (isPublicPage(currentPath)) {
        sitzungVerwerfen();
      } else if (ohneSprache(currentPath) !== "/login") {
        verlassen("/login");
      }
    }

    // Only the expired test access redirects, every other 403 stays a plain error.
    if (response.status === 403 && typeof window !== "undefined") {
      const detail = await response
        .clone()
        .json()
        .then((body) => (body as { detail?: unknown })?.detail)
        .catch(() => null);
      if (detail === ACCESS_EXPIRED_DETAIL) {
        // endsWith covers the locale prefix, /en/login is the same page as /login.
        const currentPath = window.location.pathname;
        if (!EXPIRY_HOME.some((p) => currentPath === p || currentPath.endsWith(p))) {
          verlassen(EXPIRED_PATH);
        }
      }
    }

    return response;
  }

  async postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    const response = await this.fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });

    await throwIfFailed(response);

    return response.json();
  }

  async getJson<T>(path: string): Promise<T> {
    const response = await this.fetch(path);

    await throwIfFailed(response);

    return response.json();
  }

  async patchJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    const response = await this.fetch(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });

    await throwIfFailed(response);

    return response.json();
  }

  async postJsonForBlob(
    path: string,
    body: unknown,
  ): Promise<{ blob: Blob; filename: string }> {
    const response = await this.fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    await throwIfFailed(response);

    return blobWithName(response, "output");
  }
}

export const api = new ApiClient(API_BASE);
export const backendApi = new ApiClient(BACKEND_BASE);

// ── Job polling helpers ────────────────────────────────────────────────────

/** The job stopped after its automatic attempts and waits for a click. */
export class JobPausedError extends Error {
  constructor(public readonly jobUuid: string, message: string) {
    super(message);
    this.name = "JobPausedError";
  }
}

export interface JobStatus {
  job_uuid: string;
  status: "pending" | "running" | "success" | "failed" | "awaiting_user" | "queued" | "waiting_retry" | "paused";
  tool: string;
  original_filename: string;
  progress: Record<string, unknown> | null;
  error: string | null;
  download_url: string | null;
  result: Record<string, unknown> | null;
  meta: Record<string, unknown> | null;
}

/** Polls a job to the end and reports every progress update. */
export async function pollJob(
  jobUuid: string,
  onProgress?: (status: JobStatus) => void,
  intervalMs = 3000,
  signal?: AbortSignal,
  onStuck?: () => void,
  stuckThresholdMs = 30_000,
): Promise<JobStatus> {
  let lastProgressJson = "";
  let lastProgressChangeAt = Date.now();

  while (true) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

    const res = await fetch(`/api/jobs/${jobUuid}`, { credentials: "include", signal });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      if (!body) {
        console.error(`Job status fetch failed with ${res.status}`);
        throw new Error(fallback("jobStatusError"));
      }
      throw _parseErrorResponse(body, res.status);
    }

    const status: JobStatus = await res.json();

    // Track progress changes for stuck detection
    const currentProgressJson = JSON.stringify(status.progress);
    if (currentProgressJson !== lastProgressJson) {
      lastProgressJson = currentProgressJson;
      lastProgressChangeAt = Date.now();
    } else if ((status.status === "running" || status.status === "pending") && onStuck && Date.now() - lastProgressChangeAt > stuckThresholdMs) {
      onStuck();
    }

    onProgress?.(status);

    if (status.status === "success") return status;
    if (status.status === "awaiting_user") return status;
    if (status.status === "paused") throw new JobPausedError(jobUuid, status.error || fallback("jobFailed"));
    if (status.status === "failed") throw new Error(status.error || fallback("jobFailed"));

    await new Promise<void>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout>;
      const onAbort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
      // Detach on the normal path too, otherwise every round adds a listener.
      timer = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve(); }, intervalMs);
      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }
}

/** Downloads a result file of a finished job, "download" for the main result unless another path is given. */
export async function downloadJobAsBlob(
  jobUuid: string,
  fallbackFilename = "output",
  path = "download",
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`/api/jobs/${jobUuid}/${path}`, { credentials: "include" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (!body) {
      console.error(`Job download failed with ${res.status}`);
      throw new Error(fallback("downloadFailed"));
    }
    throw _parseErrorResponse(body, res.status);
  }

  return blobWithName(res, fallbackFilename);
}
