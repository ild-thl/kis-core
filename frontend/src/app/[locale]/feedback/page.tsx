"use client";

/** Anonymous feedback form for logged-in users, reached via footer and start page hint. */

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Paperclip, X } from "@phosphor-icons/react";
import Select, { type SelectOption } from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import IconButton from "@/components/ui/IconButton";
import Spinner from "@/components/ui/Spinner";
import { useRouter } from "@/i18n/navigation";
import { checkAuthStatus } from "@/lib/auth";

type Category = "bug" | "idea" | "other";

const MAX_MESSAGE_CHARS = 2000;
// Five files of 5 MiB stay under the 32 MB proxy limit, the backend checks the same.
const MAX_FILES = 5;
const MAX_FILE_MB = 5;
const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;
const ACCEPT = ".png,.jpg,.jpeg,.pdf,image/png,image/jpeg,application/pdf";

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FeedbackPage() {
  const t = useTranslations("feedback");
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [category, setCategory] = useState<Category>("bug");
  const [message, setMessage] = useState("");
  const [contact, setContact] = useState("");
  const [includeUsername, setIncludeUsername] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [pagePath, setPagePath] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    checkAuthStatus().then((status) => {
      if (!status.authenticated) router.replace("/login");
      else setReady(true);
    });
  }, [router]);

  useEffect(() => {
    if (!document.referrer) return;
    try {
      const url = new URL(document.referrer);
      if (url.origin === window.location.origin) setPagePath(url.pathname);
    } catch {
      /* no valid referrer, page_path stays empty */
    }
  }, []);

  const options: SelectOption<Category>[] = useMemo(
    () => [
      { value: "bug", label: t("categoryBug") },
      { value: "idea", label: t("categoryIdea") },
      { value: "other", label: t("categoryOther") },
    ],
    [t],
  );

  function addFiles(picked: FileList | null) {
    if (!picked || picked.length === 0) return;
    setError("");
    const naechste = [...files];
    for (const datei of Array.from(picked)) {
      if (naechste.length >= MAX_FILES) {
        setError(t("tooManyFiles", { max: MAX_FILES }));
        break;
      }
      if (datei.size > MAX_FILE_BYTES) {
        setError(t("fileTooLarge", { name: datei.name, max: MAX_FILE_MB }));
        continue;
      }
      naechste.push(datei);
    }
    setFiles(naechste);
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function submit() {
    if (!message.trim()) {
      setError(t("messageRequired"));
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const body = new FormData();
      body.append("category", category);
      body.append("message", message.trim());
      if (contact.trim()) body.append("contact", contact.trim());
      if (includeUsername) body.append("include_username", "true");
      if (pagePath) body.append("page_path", pagePath);
      files.forEach((datei) => body.append("files", datei));

      const r = await fetch("/api/feedback", {
        method: "POST",
        credentials: "include",
        body,
      });
      if (!r.ok) throw new Error("failed");
      setSubmitted(true);
    } catch {
      setError(t("submitError"));
    } finally {
      setSubmitting(false);
    }
  }

  if (!ready) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <h1 className="text-2xl font-bold mb-3">{t("thanksTitle")}</h1>
        <p className="text-foreground-soft">{t("thanksBody")}</p>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="bg-background rounded-xl shadow-sm border border-border-soft p-8">
        <h1 className="text-2xl font-bold mb-2">{t("title")}</h1>
        <p className="text-sm text-foreground-soft mb-6">{t("intro")}</p>

        <div className="space-y-5">
          <label className="block space-y-1">
            <span className="text-xs uppercase tracking-wide text-muted">{t("categoryLabel")}</span>
            <Select<Category> value={category} onChange={setCategory} options={options} />
          </label>

          <label className="block space-y-1">
            <span className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wide text-muted">{t("messageLabel")}</span>
              <span className="text-2xs text-muted-soft">{message.length} / {MAX_MESSAGE_CHARS}</span>
            </span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value.slice(0, MAX_MESSAGE_CHARS))}
              maxLength={MAX_MESSAGE_CHARS}
              rows={6}
              placeholder={t("messagePlaceholder")}
              className="w-full rounded-lg border-2 border-border bg-background px-3 py-2 text-sm text-foreground transition-colors hover:border-kb focus:outline-none focus:border-kb resize-y"
            />
          </label>

          <div className="space-y-2">
            <span className="text-xs uppercase tracking-wide text-muted">{t("attachLabel")}</span>
            <label className="inline-flex items-center gap-2 text-sm text-kb cursor-pointer">
              <Paperclip size={16} />
              {t("attachButton")}
              <input
                type="file"
                multiple
                accept={ACCEPT}
                onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
                className="hidden"
              />
            </label>
            <p className="text-xs text-muted-soft">{t("attachHint", { max: MAX_FILES, mb: MAX_FILE_MB })}</p>
            {files.length > 0 && (
              <ul className="space-y-1.5">
                {files.map((datei, i) => (
                  <li
                    key={`${datei.name}-${i}`}
                    className="flex items-center justify-between gap-2 rounded-lg border border-border-soft px-3 py-1.5 text-xs"
                  >
                    <span className="truncate">{datei.name}</span>
                    <span className="flex items-center gap-2 shrink-0 text-muted-soft">
                      {formatSize(datei.size)}
                      <IconButton
                        size="sm"
                        onClick={() => removeFile(i)}
                        aria-label={t("removeFile")}
                      >
                        <X size={13} />
                      </IconButton>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <label className="block space-y-1">
            <span className="text-xs uppercase tracking-wide text-muted">{t("contactLabel")}</span>
            <input
              type="text"
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder={t("contactPlaceholder")}
              className="w-full rounded-lg border-2 border-border bg-background px-3 py-2 text-sm text-foreground transition-colors hover:border-kb focus:outline-none focus:border-kb"
            />
            <span className="block text-xs text-muted-soft">{t("contactHint")}</span>
          </label>

          <Checkbox
            checked={includeUsername}
            onChange={setIncludeUsername}
            label={t("includeUsernameLabel")}
          />
          <p className="-mt-3 text-xs text-muted-soft">{t("includeUsernameHint")}</p>

          {error && <p className="text-sm text-error">{error}</p>}

          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting}
            className="btn-primary px-6 py-2.5 rounded-lg text-sm font-medium disabled:opacity-50"
          >
            {submitting ? t("submitting") : t("submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
