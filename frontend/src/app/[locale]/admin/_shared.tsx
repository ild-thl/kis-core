"use client";

import { useTranslations } from "next-intl";
import StatusMark from "@/components/ui/StatusMark";
import { jobStatusDisplay } from "@/lib/jobStatusDisplay";

export interface PendingUser {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  created_at: string;
}

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  active: number;
  created_at: string;
  role?: "admin" | "staff" | "user" | "custom";
  custom_role_id?: number | null;
  is_demo?: boolean;
  can_reset_link?: boolean;
}

export interface AdminJob {
  job_uuid: string;
  tool: string;
  tool_label: string;
  original_filename: string;
  status: string;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  user_display_name: string;
}

export function JobStatusBadge({ status }: { status: string }) {
  const t = useTranslations("admin.jobStatus");
  const anzeige = jobStatusDisplay(status, {});
  // The admin area only shows the states it has labels for.
  const key = anzeige.kind === "action" ? "pending" : anzeige.key;
  const tone = anzeige.kind === "action" ? "warn" : anzeige.tone;
  return (
    <StatusMark tone={tone} pulse={anzeige.kind === "mark" && anzeige.pulse} className="text-xs">
      {t(key as "success" | "failed" | "running" | "queued" | "pending" | "waitingRetry")}
    </StatusMark>
  );
}
