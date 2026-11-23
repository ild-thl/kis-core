"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Link } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { Eye, EyeSlash } from "@phosphor-icons/react";
import AuthSplit from "@/components/layout/AuthSplit";
import Tabs from "@/components/ui/Tabs";
import { login, checkAuthStatus } from "@/lib/auth";
import { AccessCodeDone, AccessCodeForm, useAccessCode } from "../redeem/_accessCode";
import { isReturnPath } from "@/components/auth/_routeGuard";
import { AUTH_FIELD } from "@/components/auth/authField";

/** Where the login leads: back to a shared page the person came from, else the workspaces. */
function afterLogin(): string {
  const next = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("next");
  return isReturnPath(next) ? next : "/workspace";
}

export default function LoginPage() {
  const t = useTranslations("login");
  const tc = useTranslations("accessCode");
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [loading, setLoading] = useState(false);
  const [maintenanceOn, setMaintenanceOn] = useState(false);
  const [abgelaufen, setAbgelaufen] = useState(false);
  const [tab, setTab] = useState<"login" | "code">("login");
  const accessCode = useAccessCode();
  const { setCode, fertig, redeem } = accessCode;

  useEffect(() => {
    checkAuthStatus().then((status) => {
      if (status.authenticated) router.replace(afterLogin());
      else setChecking(false);
    });
  }, [router]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/health/maintenance", { cache: "no-store" });
        if (!res.ok) return;
        const d = await res.json();
        if (!cancelled) setMaintenanceOn(!!d.enabled);
      } catch {
        /* ignore */
      }
    };
    poll();
    const id = setInterval(poll, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Whoever was thrown out by an expired access arrives with this marker in the address.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("expired")) setAbgelaufen(true);
  }, []);

  // A QR code links here with the code in the address, that opens the code tab and redeems it at once.
  const autoDone = useRef(false);
  useEffect(() => {
    // A plain link only fills in the code tab, the person presses the button themselves.
    const prefill = new URLSearchParams(window.location.search).get("vorbelegt");
    if (prefill) {
      setTab("code");
      setCode(prefill);
    }
  }, []);

  useEffect(() => {
    const fromLink = new URLSearchParams(window.location.search).get("code");
    if (fromLink && !autoDone.current) {
      autoDone.current = true;
      setTab("code");
      setCode(fromLink);
      checkAuthStatus().then((s) => (s.authenticated ? window.location.assign("/workspace") : redeem(fromLink)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username.trim(), password);
      await checkAuthStatus();
      // A hard navigation so the server reads the new session cookie.
      window.location.assign(afterLogin());
      return;
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      if (message === "account_not_activated") router.push("/pending");
      else if (message === "access_expired") setAbgelaufen(true);
      else if (maintenanceOn) setError(t("maintenanceBanner"));
      else setError(t("invalidCredentials"));
    } finally {
      setLoading(false);
    }
  };

  if (checking) return null;

  return (
    <AuthSplit heading={t("welcome")} hideLogin>
      <h2 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">
        {fertig ? tc("doneTitle") : t("title")}
      </h2>
      {!fertig && (
        <Tabs
          items={[
            { key: "login", label: t("tabAccount") },
            { key: "code", label: t("tabCode") },
          ]}
          active={tab}
          onChange={setTab}
          className="mt-5 text-base"
        />
      )}

      {tab === "login" && abgelaufen && (
        <div
          role="status"
          data-testid="login-expired"
          className="mt-5 rounded-lg border-2 border-border bg-surface-dim p-4 text-foreground"
        >
          <p className="text-sm font-semibold">{t("expiredTitle")}</p>
          <p className="mt-1 text-sm leading-relaxed text-foreground-soft">{t("expiredText")}</p>
          <a href="mailto:hamid.mergan@th-luebeck.de" className="mt-2 inline-block text-sm text-kb-dark hover:underline">
            hamid.mergan@th-luebeck.de
          </a>
        </div>
      )}

      {tab === "login" && (
      <form onSubmit={handleSubmit} aria-label={t("formAria")} className="mt-6 space-y-5">
        <div>
          <label htmlFor="username" className="block text-sm font-medium text-foreground-soft mb-1.5">
            {t("username")}
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            autoFocus
            required
            disabled={loading}
            className={AUTH_FIELD}
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium text-foreground-soft mb-1.5">
            {t("password")}
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              disabled={loading}
              aria-describedby={error ? "login-error" : undefined}
              className={`${AUTH_FIELD} pr-11`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? t("hidePassword") : t("showPassword")}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-muted hover:text-kb transition-colors"
              tabIndex={-1}
            >
              {showPassword ? <EyeSlash size={20} aria-hidden="true" /> : <Eye size={20} aria-hidden="true" />}
            </button>
          </div>
        </div>

        {error && (
          <p id="login-error" className="text-sm text-error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading || !username.trim() || !password}
          className="w-full px-4 py-3 text-base font-medium btn-primary rounded-lg"
        >
          {loading ? t("submitting") : t("submit")}
        </button>
      </form>
      )}

      {tab === "code" && !fertig && <AccessCodeForm state={accessCode} />}

      {fertig && <AccessCodeDone fertig={fertig} />}

      {tab === "login" && !fertig && (
        <p className="mt-6 text-sm text-foreground-soft">
          {t("forgot")}{" "}
          <a href="mailto:hamid.mergan@th-luebeck.de" className="text-kb-dark hover:underline">
            hamid.mergan@th-luebeck.de
          </a>
        </p>
      )}

      <Link href="/" className="mt-6 inline-block text-sm text-kb-dark hover:underline">
        {t("toHome")}
      </Link>
    </AuthSplit>
  );
}
