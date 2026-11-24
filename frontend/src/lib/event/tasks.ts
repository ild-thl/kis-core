"use client";

import { useCallback, useEffect, useState } from "react";

/** The three tasks in the order of the card. */
export const TASK_IDS = ["question", "praesentation", "screencast"] as const;
export type TaskId = (typeof TASK_IDS)[number];
type ClientTaskId = Exclude<TaskId, "question">;

/** What the server sends the services page, only accounts from the card's access code see it. */
type TaskView =
  | { visible: false }
  | {
      visible: true;
      done: Partial<Record<TaskId, number>>;
      completedAt: number | null;
      workspace: string;
      workspaceTitle: string;
    };

const HIDDEN: TaskView = { visible: false };

async function request(path: string, init?: RequestInit): Promise<TaskView> {
  const res = await fetch(`/api/event-tasks${path}`, { credentials: "include", cache: "no-store", ...init });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as TaskView;
}

const taskApi = {
  read: () => request(""),
  tick: (id: ClientTaskId) => request(`/${id}`, { method: "POST" }),
};

/** The card for the services page, hidden while loading or when the server fails. */
export function useEventTasks(): TaskView {
  const [view, setView] = useState<TaskView>(HIDDEN);
  useEffect(() => {
    let alive = true;
    taskApi.read().then((v) => alive && setView(v)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return view;
}

/** Ticks a demo task once its page opens, a failure stays silent. */
export function useTickEventTask(id: ClientTaskId) {
  useEffect(() => {
    taskApi.tick(id).catch(() => {});
  }, [id]);
}

const MIN_KEY = "askf.event.tasks.min";

/** Whether this browser folded the card away, open on the first visit. */
export function useTaskCardMinimized(): [boolean, (next: boolean) => void] {
  const [min, setMin] = useState(false);
  useEffect(() => {
    try {
      setMin(localStorage.getItem(MIN_KEY) === "1");
    } catch {
      // Blocked storage, the card then opens on every visit.
    }
  }, []);
  const set = useCallback((next: boolean) => {
    setMin(next);
    try {
      localStorage.setItem(MIN_KEY, next ? "1" : "0");
    } catch {
      // Blocked storage, the choice lasts until the page closes.
    }
  }, []);
  return [min, set];
}
