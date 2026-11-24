"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { checkAuthStatus } from "@/lib/auth";
import type { AuthStatus } from "@/types";
import type { WorkspaceDetail, Source } from "../_types";
import type { Note } from "../_components/studio/NotesStudio";

interface WorkspaceSettings {
  chat_lang: "de" | "en";
  studio_enabled: boolean;
  popup_translate_lang: string;
}

interface UseWorkspaceInitOptions {
  uuid: string;
  /** Arrived via the tour link (?tour=1): join the demo course first, the fetch
   * below would otherwise turn away someone who never enrolled. */
  tourAngefordert?: boolean;
  setSources: (srcs: Source[]) => void;
  setSelectedSourceIds: (ids: string[]) => void;
  setWorkspaceDetail: (m: WorkspaceDetail) => void;
  setNotes: (notes: Note[]) => void;
  loadMessages: () => Promise<void>;
  onSettingsLoaded: (s: WorkspaceSettings) => void;
}

export function useWorkspaceInit(opts: UseWorkspaceInitOptions) {
  const {
    uuid, tourAngefordert, setSources, setSelectedSourceIds, setWorkspaceDetail,
    setNotes, loadMessages, onSettingsLoaded,
  } = opts;
  const router = useRouter();

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [initialized, setInitialized] = useState(false);
  // A closed room, not a missing permission, so the page says so instead of discarding.
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        const authData = await checkAuthStatus();
        if (cancelled) return;
        if (!authData.authenticated) { router.push("/login"); return; }
        setAuth(authData);

        if (tourAngefordert) {
          // Best-effort: on an already-owned or already-joined course this
          // 404s or no-ops, the fetch below decides access either way.
          await fetch("/api/ai-assistant/demo/enroll", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workspace_uuid: uuid }),
          }).catch(() => { /* no demo course or already enrolled, the next request settles it */ });
        }

        const modRes = await fetch(`/api/ai-assistant/workspaces/${uuid}`, { credentials: "include" });
        if (cancelled) return;
        if (modRes.status === 423) { setLocked(true); return; }
        if (!modRes.ok) { router.push("/workspace"); return; }
        const mod: WorkspaceDetail = await modRes.json();
        setWorkspaceDetail(mod);

        const srcs: Source[] = mod.sources ?? [];
        setSources(srcs);
        setSelectedSourceIds(restoreSelectedSources(uuid, srcs));

        await loadMessages();

        const settingsRes = await fetch(`/api/ai-assistant/workspaces/${uuid}/settings`, { credentials: "include" });
        if (!cancelled && settingsRes.ok) {
          const s: Partial<WorkspaceSettings> = await settingsRes.json();
          onSettingsLoaded({
            chat_lang: s.chat_lang ?? "de",
            studio_enabled: s.studio_enabled ?? true,
            popup_translate_lang: s.popup_translate_lang ?? "en",
          });
        }

        const notesRes = await fetch(`/api/ai-assistant/workspaces/${uuid}/notes`, { credentials: "include" });
        if (!cancelled && notesRes.ok) setNotes(await notesRes.json());

        if (!cancelled) setInitialized(true);
      } catch {
        if (!cancelled) router.push("/workspace");
      }
    }

    init();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uuid, router, loadMessages]);

  return { auth, initialized, locked };
}

// Restores the remembered selection, otherwise all ready sources without the running ones.
function restoreSelectedSources(uuid: string, srcs: Source[]): string[] {
  const storageKey = `askf-selected-sources-${uuid}`;
  const isFullyReady = (s: Source) => s.status === "ready" && !s.progress;
  const allReady = () => srcs.filter(isFullyReady).map((s) => s.uuid);
  const saved = sessionStorage.getItem(storageKey);
  if (!saved) return allReady();
  try {
    const savedIds: string[] = JSON.parse(saved);
    const validIds = savedIds.filter((id) => srcs.some((s) => s.uuid === id && isFullyReady(s)));
    return validIds.length > 0 ? validIds : allReady();
  } catch {
    return allReady();
  }
}
