"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Copy, Check, Warning } from "@phosphor-icons/react";
import Select from "@/components/ui/Select";
import { copyTextFromPromise } from "@/lib/clipboard";
import { useRoleOptions } from "./useRoleOptions";

type Props = {
  onClose: () => void;
};

type RoleSelection =
  | { kind: "system"; value: "staff" | "user" }
  | { kind: "custom"; customRoleId: number };

type FormState = {
  uid: string;
  given_name: string;
  surname: string;
  email: string;
  role: RoleSelection;
};

const EMPTY: FormState = {
  uid: "",
  given_name: "",
  surname: "",
  email: "",
  role: { kind: "system", value: "staff" },
};

function roleToSelectValue(r: RoleSelection): string {
  return r.kind === "system" ? r.value : `custom:${r.customRoleId}`;
}

function roleFromSelectValue(value: string): RoleSelection {
  if (value === "staff" || value === "user") {
    return { kind: "system", value };
  }
  if (value.startsWith("custom:")) {
    return { kind: "custom", customRoleId: Number(value.slice("custom:".length)) };
  }
  return { kind: "system", value: "staff" };
}

export default function CreateAccountDialog({ onClose }: Props) {
  const t = useTranslations("admin.createAccount");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{ uid: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const roleOptions = useRoleOptions(t("roleStaff"), t("roleUser"));

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const body = {
      uid: form.uid,
      given_name: form.given_name,
      surname: form.surname,
      email: form.email.trim() || null,
      ...(form.role.kind === "system"
        ? { askf_role: form.role.value }
        : { askf_role: "custom", custom_role_id: form.role.customRoleId }),
    };
    try {
      const r = await fetch("/api/admin/accounts", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        const resp = await r.json();
        setSuccess({ uid: resp.uid, password: resp.generated_password });
      } else {
        const errBody = await r.json().catch(() => ({}));
        const detail = typeof errBody?.detail === "string" ? errBody.detail : null;
        setError(detail ?? t("errorGeneric"));
      }
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setSubmitting(false);
    }
  }

  function copyPassword() {
    if (!success) return;
    copyTextFromPromise(Promise.resolve(success.password));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background border border-border rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        {success ? (
          <>
            <h2 className="text-lg font-semibold">{t("successTitle")}</h2>
            <p className="text-sm text-muted-soft">uid: <span className="font-mono">{success.uid}</span></p>

            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wide text-muted">{t("successPasswordLabel")}</label>
              <div className="flex items-center gap-2">
                <code className="flex-1 font-mono text-sm bg-surface border border-border rounded-md px-3 py-2 select-all">
                  {success.password}
                </code>
                <button
                  type="button"
                  onClick={copyPassword}
                  className="px-3 py-2 text-sm border-2 border-border rounded-md hover:border-[var(--kb)] hover:text-[var(--kb)] flex items-center gap-1"
                >
                  {copied ? <Check size={16} weight="bold" /> : <Copy size={16} weight="bold" />}
                  {copied ? t("successCopied") : t("successCopyButton")}
                </button>
              </div>
            </div>

            <div className="flex items-start gap-2 bg-warn-bg text-warn-strong text-sm rounded-md px-3 py-2">
              <Warning size={18} weight="bold" className="mt-0.5 shrink-0" />
              <span>{t("successWarning")}</span>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm btn-primary rounded-md transition-colors"
              >
                {t("successClose")}
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <h2 className="text-lg font-semibold">{t("title")}</h2>

            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wide text-muted">{t("fieldUid")}</label>
              <input
                type="text"
                required
                value={form.uid}
                onChange={(e) => update("uid", e.target.value.toLowerCase())}
                pattern="[a-z0-9_.\-]{2,32}"
                className="w-full text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb font-mono"
              />
              <p className="text-xs text-muted-soft">{t("fieldUidHint")}</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs uppercase tracking-wide text-muted">{t("fieldGivenName")}</label>
                <input
                  type="text"
                  required
                  value={form.given_name}
                  onChange={(e) => update("given_name", e.target.value)}
                  className="w-full text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs uppercase tracking-wide text-muted">{t("fieldSurname")}</label>
                <input
                  type="text"
                  required
                  value={form.surname}
                  onChange={(e) => update("surname", e.target.value)}
                  className="w-full text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wide text-muted">
                {t("fieldEmail")} <span className="normal-case">{t("emailOptional")}</span>
              </label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                className="w-full text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs uppercase tracking-wide text-muted">{t("fieldRole")}</label>
              <Select
                value={roleToSelectValue(form.role)}
                onChange={(v) => update("role", roleFromSelectValue(v))}
                options={roleOptions}
                className="w-full"
              />
            </div>

            {error && (
              <p className="text-sm text-error">{error}</p>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="px-4 py-2 text-sm border-2 border-border rounded-md hover:border-[var(--kb)] hover:text-[var(--kb)]"
              >
                {t("cancel")}
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 text-sm btn-primary rounded-md transition-colors disabled:opacity-60"
              >
                {t("submit")}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
