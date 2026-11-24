import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appendFile, appendFiles, forgetUpload, uploadFile } from "./directUpload";

const BASE = "/api/uploads";
const PART = 5 * 1024 * 1024;

function fileOf(size: number, name = "vortrag.mp3"): File {
  return new File([new Uint8Array(size)], name, { lastModified: 1 });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let store: Record<string, string>;
let calls: { url: string; method: string; size?: number; body?: string }[];

beforeEach(() => {
  store = {};
  calls = [];
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** A server that opens an upload of `count` parts and accepts every PUT. */
function serverWith(opts: { count: number; uploaded?: number[]; done?: boolean; putStatus?: () => number; completeStatus?: number }) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body as Blob | string | undefined;
    calls.push({ url, method, size: body instanceof Blob ? body.size : undefined, body: typeof body === "string" ? body : undefined });
    if (url === BASE && method === "POST") {
      return json({ direct: true, token: "tok", part_size: PART, part_count: opts.count, uploaded: [] });
    }
    if (url === `${BASE}/tok` && method === "GET") {
      return json({ direct: true, token: "tok", part_size: PART, part_count: opts.count, uploaded: opts.uploaded ?? [], done: opts.done ?? false });
    }
    if (url === `${BASE}/tok/urls`) {
      const parts = (JSON.parse(body as string) as { parts: number[] }).parts;
      return json({ urls: Object.fromEntries(parts.map((n) => [String(n), `https://bucket/part/${n}`])) });
    }
    if (url === `${BASE}/tok/complete`) return json({ token: "tok", done: true }, opts.completeStatus ?? 200);
    if (url.startsWith("https://bucket/part/")) return new Response(null, { status: opts.putStatus?.() ?? 200 });
    return new Response(null, { status: 404 });
  }));
}

const run = (file: File, extra: Partial<Parameters<typeof uploadFile>[0]> = {}) =>
  uploadFile({ tool: "transcription", file, failedText: "Fehler", ...extra });

describe("uploadFile", () => {
  it("schickt die Datei in Teilen von 5 MiB, schließt ab und gibt das Token zurück", async () => {
    serverWith({ count: 3 });
    const percents: number[] = [];
    const token = await run(fileOf(PART * 2 + 5), { onPercent: (p) => percents.push(p) });
    expect(token).toBe("tok");
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts.map((c) => c.size)).toEqual([PART, PART, 5]);
    // No single request is bigger than a part, so a proxy limit of 32 MiB never matters.
    expect(Math.max(...puts.map((c) => c.size ?? 0))).toBeLessThanOrEqual(PART);
    expect(calls.at(-1)?.url).toBe(`${BASE}/tok/complete`);
    expect(percents.at(-1)).toBe(100);
  });

  it("meldet Werkzeug und Zusatzangaben bei der Anmeldung", async () => {
    serverWith({ count: 1 });
    await run(fileOf(10), { tool: "aia", context: { workspace_uuid: "w1" } });
    const start = JSON.parse(calls[0].body as string);
    expect(start).toEqual({ tool: "aia", filename: "vortrag.mp3", size: 10, context: { workspace_uuid: "w1" } });
  });

  it("gibt null zurück, wenn der Server den klassischen Weg will", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ direct: false })));
    expect(await run(fileOf(10))).toBeNull();
  });

  it("macht dort weiter, wo ein abgebrochener Upload stand", async () => {
    const file = fileOf(PART * 2 + 5);
    store[`askf-upload:transcription::${file.name}:${file.size}:${file.lastModified}`] = "tok";
    serverWith({ count: 3, uploaded: [1, 2] });
    expect(await run(file)).toBe("tok");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    expect(calls.some((c) => c.method === "POST" && c.url === BASE)).toBe(false);
  });

  it("schließt einen schon fertigen Upload nur noch ab, ohne Teile", async () => {
    const file = fileOf(PART + 1);
    store[`askf-upload:transcription::${file.name}:${file.size}:${file.lastModified}`] = "tok";
    serverWith({ count: 2, uploaded: [1, 2], done: true });
    expect(await run(file)).toBe("tok");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
  });

  it("fällt auf den klassischen Weg zurück, wenn der Bucket den Browser gleich ablehnt", async () => {
    serverWith({ count: 2 });
    const base = vi.mocked(fetch).getMockImplementation()!;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith("https://bucket/part/")) throw new TypeError("Failed to fetch");
      return base(url, init);
    }));
    expect(await run(fileOf(PART + 1))).toBeNull();
  });

  it("wiederholt einen fehlgeschlagenen Teil und gibt am Ende auf", async () => {
    vi.useFakeTimers();
    serverWith({ count: 1, putStatus: () => 500 });
    const outcome = run(fileOf(10), { failedText: "Upload fehlgeschlagen" }).then(() => "ok", (e: Error) => e.message);
    await vi.runAllTimersAsync();
    expect(await outcome).toBe("Upload fehlgeschlagen");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(8);
  });

  it("behält das Token, wenn beim Abschluss noch Teile fehlen", async () => {
    serverWith({ count: 1, completeStatus: 409 });
    const file = fileOf(10);
    await expect(run(file)).rejects.toThrow();
    expect(Object.keys(store)).toHaveLength(1);
  });
});

describe("forgetUpload", () => {
  it("löscht das gemerkte Token einer Datei", async () => {
    serverWith({ count: 1 });
    const file = fileOf(10);
    await run(file);
    expect(Object.keys(store)).toHaveLength(1);
    forgetUpload("transcription", file);
    expect(Object.keys(store)).toHaveLength(0);
  });
});

describe("appendFile und appendFiles", () => {
  it("hängt das Token an, wenn der Teile-Upload klappt", async () => {
    serverWith({ count: 1 });
    const fd = new FormData();
    const forget = await appendFile(fd, { tool: "translation", file: fileOf(10), failedText: "x" });
    expect(fd.get("upload_token")).toBe("tok");
    expect(fd.get("file")).toBeNull();
    forget();
    expect(Object.keys(store)).toHaveLength(0);
  });

  it("hängt die Datei klassisch an, wenn der Server das will", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ direct: false })));
    const fd = new FormData();
    await appendFile(fd, { tool: "translation", file: fileOf(10), failedText: "x" });
    expect(fd.get("upload_token")).toBeNull();
    expect(fd.get("file")).toBeInstanceOf(File);
  });

  it("schickt mehrere Dateien je als Token", async () => {
    serverWith({ count: 1 });
    const fd = new FormData();
    await appendFiles(fd, { tool: "summary", files: [fileOf(10, "a.pdf"), fileOf(12, "b.pdf")], failedText: "x" });
    expect(fd.getAll("upload_tokens")).toEqual(["tok", "tok"]);
    expect(fd.getAll("files")).toEqual([]);
  });
});
