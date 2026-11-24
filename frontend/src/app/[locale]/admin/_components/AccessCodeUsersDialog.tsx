"use client";

/** The accounts one access code created: login on or off, new password, delete, one by one or all at once. */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Trash } from "@phosphor-icons/react";
import Spinner from "@/components/ui/Spinner";
import Modal from "@/components/ui/Modal";
import IconButton from "@/components/ui/IconButton";
import StatusMark from "@/components/ui/StatusMark";
import type { StatusTone } from "@/lib/jobStatusDisplay";
import { copyTextFromPromise } from "@/lib/clipboard";

type KontoZustand = "active" | "expired" | "disabled";

type Konto = {
  id: number;
  username: string;
  created_at: string;
  access_expires_at: string | null;
  active: boolean | number;
  status: KontoZustand;
  /** When the nightly sweep removes the account, null while nothing removes it. */
  delete_at: string | null;
};

const TON_KONTO: Record<KontoZustand, StatusTone> = {
  active: "brand",
  expired: "muted",
  disabled: "muted",
};

export type KontenUmfang = { id: number; label: string; code: string };

type Rueckfrage = { art: "lock" | "delete" } | { art: "deleteOne"; konto: Konto };

type Props = {
  umfang: KontenUmfang;
  onClose: () => void;
};

function datum(wert: string): string {
  return new Date(wert).toLocaleDateString("de-DE");
}

export default function AccessCodeUsersDialog({ umfang, onClose }: Props) {
  const t = useTranslations("admin.accessCodes");
  const [konten, setKonten] = useState<Konto[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [resettingId, setResettingId] = useState<number | null>(null);
  const [neuePasswoerter, setNeuePasswoerter] = useState<Record<number, string>>({});
  const [kopiertNutzer, setKopiertNutzer] = useState<number | null>(null);
  const [kopiertPasswort, setKopiertPasswort] = useState<number | null>(null);
  const [schaltend, setSchaltend] = useState<number | null>(null);
  const [rueckfrage, setRueckfrage] = useState<Rueckfrage | null>(null);
  const [arbeitet, setArbeitet] = useState(false);

  const adresse = `/api/admin/access-codes/${umfang.id}/users`;

  const laden = useCallback(() => {
    setError("");
    fetch(adresse, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("load"))))
      .then((d) => setKonten(d.users ?? []))
      .catch(() => setError(t("usersLoadError")))
      .finally(() => setLoading(false));
  }, [adresse, t]);

  useEffect(laden, [laden]);

  function kopierenNutzer(konto: Konto) {
    copyTextFromPromise(Promise.resolve(konto.username));
    setKopiertNutzer(konto.id);
    setTimeout(() => setKopiertNutzer(null), 1500);
  }

  function kopierenPasswort(konto: Konto, passwort: string) {
    copyTextFromPromise(Promise.resolve(passwort));
    setKopiertPasswort(konto.id);
    setTimeout(() => setKopiertPasswort(null), 1500);
  }

  async function passwortZuruecksetzen(konto: Konto) {
    setResettingId(konto.id);
    setError("");
    try {
      const r = await fetch(`/api/admin/access-codes/users/${konto.id}/password`, {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) {
        setError(t("resetError"));
        return;
      }
      const d = await r.json();
      setNeuePasswoerter((prev) => ({ ...prev, [konto.id]: d.password }));
    } catch {
      setError(t("resetError"));
    } finally {
      setResettingId(null);
    }
  }

  async function anmeldungUmschalten(konto: Konto) {
    setSchaltend(konto.id);
    setError("");
    try {
      const r = await fetch(`/api/admin/access-codes/users/${konto.id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !konto.active }),
      });
      if (!r.ok) {
        setError(t("saveError"));
        return;
      }
      laden();
    } catch {
      setError(t("saveError"));
    } finally {
      setSchaltend(null);
    }
  }

  async function bestaetigen() {
    if (!rueckfrage) return;
    setArbeitet(true);
    setError("");
    try {
      const r =
        rueckfrage.art === "deleteOne"
          ? await fetch(`/api/admin/access-codes/users/${rueckfrage.konto.id}`, {
              method: "DELETE",
              credentials: "include",
            })
          : await fetch("/api/admin/access-codes/users/bulk", {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ action: rueckfrage.art, code_id: umfang.id }),
            });
      setRueckfrage(null);
      laden();
      // After the reload, which clears the error line when it starts.
      if (!r.ok) setError(t("saveError"));
    } catch {
      setError(t("saveError"));
      setRueckfrage(null);
    } finally {
      setArbeitet(false);
    }
  }

  const anzahlAktiv = konten.filter((k) => k.active).length;
  const rueckfrageText =
    rueckfrage?.art === "lock"
      ? t("lockAllText", { n: anzahlAktiv })
      : rueckfrage?.art === "delete"
        ? t("deleteAllText", { n: konten.length })
        : rueckfrage?.art === "deleteOne"
          ? t("deleteUserText", { name: rueckfrage.konto.username })
          : "";

  return (
    <>
      <Modal
        open
        onClose={onClose}
        title={umfang.label}
        size="xl"
        footer={
          <button type="button" onClick={onClose} className="btn-cancel px-4 py-2 text-sm btn-secondary rounded-lg">
            {t("close")}
          </button>
        }
      >
        <div data-testid="access-code-users">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <p className="text-xs text-muted-soft">
              <span className="font-mono">{umfang.code}</span>
            </p>
            {konten.length > 0 && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  data-testid="access-code-users-lock-all"
                  onClick={() => setRueckfrage({ art: "lock" })}
                  disabled={anzahlAktiv === 0}
                  className="btn-cancel px-4 py-2 text-sm btn-secondary rounded-lg disabled:opacity-50"
                >
                  {t("lockAll")}
                </button>
                <button
                  type="button"
                  data-testid="access-code-users-delete-all"
                  onClick={() => setRueckfrage({ art: "delete" })}
                  className="px-4 py-2 text-sm btn-danger rounded-lg"
                >
                  {t("deleteAll")}
                </button>
              </div>
            )}
          </div>

          {error && <p className="text-xs text-error mb-2">{error}</p>}

          {loading ? (
            <Spinner className="flex justify-center py-8" />
          ) : konten.length === 0 ? (
            <p className="text-sm text-muted-soft text-center py-6">{t("usersEmpty")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border border-border-soft rounded-xl overflow-hidden">
                <thead className="bg-surface text-xs text-muted uppercase">
                  <tr>
                    <th className="px-3 py-2 text-left">{t("colUser")}</th>
                    <th className="px-3 py-2 text-left">{t("colCreated")}</th>
                    <th className="px-3 py-2 text-left">{t("colExpires")}</th>
                    <th className="px-3 py-2 text-left">{t("colDeleteAt")}</th>
                    <th className="px-3 py-2 text-left">{t("colLogin")}</th>
                    <th className="px-3 py-2 text-left">{t("resetPassword")}</th>
                    <th className="px-3 py-2 text-left"><span className="sr-only">{t("deleteUser")}</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-soft bg-background">
                  {konten.map((k) => (
                    <tr key={k.id} data-testid="access-code-user-row">
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => kopierenNutzer(k)}
                          aria-label={t("copyUser")}
                          className="font-mono text-foreground-soft hover:text-kb inline-flex items-center gap-1.5 rounded focus:outline-none focus:ring-2 focus:ring-kb"
                        >
                          {k.username}
                          {kopiertNutzer === k.id && <Check size={12} weight="bold" className="text-kb" />}
                        </button>
                      </td>
                      <td className="px-3 py-2 text-foreground-soft">{datum(k.created_at)}</td>
                      <td className="px-3 py-2 text-foreground-soft">
                        {k.access_expires_at == null ? t("accessUnlimited") : datum(k.access_expires_at)}
                      </td>
                      <td className="px-3 py-2 text-foreground-soft">
                        {k.delete_at == null ? t("deleteNever") : datum(k.delete_at)}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2.5">
                          <button
                            type="button"
                            role="switch"
                            aria-checked={!!k.active}
                            aria-label={k.active ? t("lockUser") : t("unlockUser")}
                            data-testid="access-code-user-login"
                            onClick={() => anmeldungUmschalten(k)}
                            disabled={schaltend === k.id}
                            className="relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full border-2 border-transparent transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-offset-2 enabled:hover:border-kb"
                            style={{ backgroundColor: k.active ? "var(--kb)" : "var(--border)" }}
                          >
                            <span
                              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                                k.active ? "translate-x-[1.125rem]" : "translate-x-0.5"
                              }`}
                            />
                          </button>
                          <StatusMark tone={TON_KONTO[k.status]} className="text-xs">
                            {t(`state${k.status[0].toUpperCase()}${k.status.slice(1)}` as
                              "stateActive" | "stateExpired" | "stateDisabled")}
                          </StatusMark>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        {neuePasswoerter[k.id] ? (
                          <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs text-muted-soft">{t("newPassword")}:</span>
                              <button
                                type="button"
                                onClick={() => kopierenPasswort(k, neuePasswoerter[k.id])}
                                aria-label={t("copyPassword")}
                                className="font-mono text-foreground-soft hover:text-kb inline-flex items-center gap-1.5 rounded focus:outline-none focus:ring-2 focus:ring-kb"
                              >
                                {neuePasswoerter[k.id]}
                                {kopiertPasswort === k.id && <Check size={12} weight="bold" className="text-kb" />}
                              </button>
                            </div>
                            <span className="text-2xs text-muted-soft">{t("newPasswordOnce")}</span>
                          </div>
                        ) : (
                          <button
                            type="button"
                            data-testid="access-code-reset"
                            onClick={() => passwortZuruecksetzen(k)}
                            disabled={resettingId === k.id}
                            className="px-3 py-1.5 text-xs btn-primary rounded-md transition-colors disabled:opacity-50 whitespace-nowrap"
                          >
                            {resettingId === k.id ? t("resetting") : t("resetPassword")}
                          </button>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <IconButton
                          size="sm"
                          title={t("deleteUser")}
                          aria-label={t("deleteUser")}
                          data-testid="access-code-user-delete"
                          onClick={() => setRueckfrage({ art: "deleteOne", konto: k })}
                        >
                          <Trash size={14} weight="bold" />
                        </IconButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Modal>

      <Modal
        open={!!rueckfrage}
        onClose={() => !arbeitet && setRueckfrage(null)}
        title={rueckfrage?.art === "lock" ? t("lockAllTitle") : t("deleteUsersTitle")}
        size="sm"
        footer={
          <>
            <button
              type="button"
              onClick={() => setRueckfrage(null)}
              disabled={arbeitet}
              className="btn-cancel px-4 py-2 text-sm btn-secondary rounded-lg disabled:opacity-50"
            >
              {t("cancel")}
            </button>
            <button
              type="button"
              data-testid="access-code-users-confirm"
              onClick={() => void bestaetigen()}
              disabled={arbeitet}
              className={
                rueckfrage?.art === "lock"
                  ? "px-4 py-2 text-sm btn-primary rounded-lg disabled:opacity-50"
                  : "px-4 py-2 text-sm btn-danger rounded-lg disabled:opacity-50"
              }
            >
              {rueckfrage?.art === "lock" ? t("lockAllConfirm") : t("deleteConfirm")}
            </button>
          </>
        }
      >
        <p className="text-sm text-foreground-soft">{rueckfrageText}</p>
        {rueckfrage?.art !== "lock" && <p className="mt-2 text-xs text-muted-soft">{t("deleteUsersHint")}</p>}
      </Modal>
    </>
  );
}
