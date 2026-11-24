"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const CHANGE_EVENT = "askf-feedback:change";

/** Tells every dot that a feedback status changed, so they ask again. */
export function announceFeedbackChange() {
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Number of open feedback entries, 0 without the permission or on error. */
export function useOpenFeedback(enabled: boolean): number {
  const [open, setOpen] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setOpen(0);
      return;
    }
    let cancelled = false;
    const load = () => {
      api
        .fetch("/api/admin/feedback/open-count", { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!cancelled && data) setOpen(typeof data.open === "number" ? data.open : 0);
        })
        .catch(() => {
          /* ignore - the dot just stays as it was */
        });
    };
    load();
    window.addEventListener(CHANGE_EVENT, load);
    return () => {
      cancelled = true;
      window.removeEventListener(CHANGE_EVENT, load);
    };
  }, [enabled]);

  return open;
}
