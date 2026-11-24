export type SystemRole = "admin" | "staff" | "user" | "custom";

export interface UserPermissions {
  /** May see at least one page of the admin area, long since no longer called admin. */
  allow_admin_panel: boolean;
  allow_aia: boolean;
  allow_workspace_create: boolean;
  tools: string[]; // tool keys
  /** All permission keys, the sidebar decides per page with them. */
  keys: string[];
  /** Not a grantable permission but the permission plus the server switch. */
  allow_account_create?: boolean;
}

export interface AuthStatus {
  authenticated: boolean;
  local_mode?: boolean;
  user_id?: number;
  username?: string;
  display_name?: string;
  email?: string;
  is_admin?: boolean;
  role?: SystemRole;
  custom_role_id?: number | null;
  permissions?: UserPermissions;
  /** Which modules this installation has, missing on older servers. */
  modules?: string[];
  /** The one notice every account confirms once, before any service is reachable. */
  global_consent_accepted?: boolean;
  /** Set while somebody is logged in as this account. */
  impersonator?: Impersonator;
  /** Deadline of an access code account, null for normal accounts. */
  access_expires_at?: string | null;
  /** Why nobody is signed in, currently only "access_expired". */
  reason?: string;
}

/** Who borrowed this account, shown in the banner above every page. */
export interface Impersonator {
  user_id: number;
  username: string;
  display_name: string;
  log_id: number;
}

export interface LoginResponse {
  status: string;
  username: string;
  display_name: string;
}

export type TTSState = "idle" | "uploading" | "processing" | "done" | "error" | "paused";

export type ScreencastStep =
  | "upload"
  | "translating"
  | "user-prompt"
  | "translation-review"
  | "preparing"
  | "generating-scripts"
  | "script-review"
  | "tts-settings"
  | "rendering"
  | "done"
  | "error";

export interface GlossaryEntry {
  source: string;
  target: string;
}

export interface Glossary {
  id: string;
  name: string;
  entries: Record<string, string>;
  createdAt: string;
}

export interface SlideData {
  index: number;
  imageBase64: string;
  extractedText: string;
  script: string;
  /** The translation did not change the text of this slide, a hint and not an error. */
  unchanged?: boolean;
}
