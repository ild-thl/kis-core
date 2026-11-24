"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Checkbox from "@/components/ui/Checkbox";
import DemoConfirmDialog from "./DemoConfirmDialog";
import { Gauge, Key, SignIn, Trash, Users } from "@phosphor-icons/react";
import IconButton from "@/components/ui/IconButton";
import Select from "@/components/ui/Select";
import Spinner from "@/components/ui/Spinner";
import StatusMark from "@/components/ui/StatusMark";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDate } from "@/lib/format";
import type { AdminUser } from "../_shared";
import { canDeleteUser } from "./canDeleteUser";
import { canImpersonate, gesperrteRollenIds } from "./canImpersonate";
import { clearAuthCache } from "@/lib/auth";
import { PERM } from "@/lib/permissions";
import CreateAccountDialog from "./CreateAccountDialog";
import DeleteUserConfirmDialog from "./DeleteUserConfirmDialog";
import ResetLinkDialog from "./ResetLinkDialog";
import Pager from "./Pager";
import { useListFilter } from "./useListFilter";

export default function UsersTab({ onOpenQuota }: { onOpenQuota: (userId: number) => void }) {
  const t = useTranslations("admin");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const { q, setQ, limit, setLimit, offset, setOffset, dateFrom, setDateFrom, dateTo, setDateTo, query } = useListFilter();
  const [roleOptions, setRoleOptions] = useState<{ value: string; label: string; customId: number | null }[]>([]);
  const [adminEmail, setAdminEmail] = useState<string>("");
  const [meineId, setMeineId] = useState(0);
  const [zuLoeschen, setZuLoeschen] = useState<AdminUser | null>(null);
  const [resetFuer, setResetFuer] = useState<AdminUser | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [demoFrage, setDemoFrage] = useState<{ user: AdminUser; wert: boolean } | null>(null);
  const [allowAccountCreate, setAllowAccountCreate] = useState(false);
  const [darfUebernehmen, setDarfUebernehmen] = useState(false);
  const [gesperrteRollen, setGesperrteRollen] = useState<number[]>([]);
  const [uebernahmeFehler, setUebernahmeFehler] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const pageSizeOptions = useMemo(
    () => [
      { value: "50", label: t("users.pageSize", { n: 50 }) },
      { value: "100", label: t("users.pageSize", { n: 100 }) },
    ],
    [t],
  );

  useEffect(() => {
    // A slower answer to an older filter must not replace the newer list.
    let current = true;
    setLoading(true);
    fetch(`/api/admin/users?${query}`, { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        if (!current) return;
        setUsers(d.users ?? []);
        setTotal(d.total ?? 0);
      })
      .catch(() => {})
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [query, refreshKey]);

  useEffect(() => {
    fetch("/api/admin/roles", { credentials: "include" })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (!d) return;
        const opts = [
          { value: "admin", label: t("roles.roleAdmin"), customId: null as number | null },
          { value: "staff", label: t("roles.roleStaff"), customId: null as number | null },
          { value: "user", label: t("roles.roleUser"), customId: null as number | null },
          ...d.custom_roles.map((r: { id: number; name: string }) => ({
            value: `custom:${r.id}`,
            label: r.name,
            customId: r.id,
          })),
        ];
        setRoleOptions(opts);
        setGesperrteRollen(gesperrteRollenIds(d.custom_roles ?? []));
      });
    fetch("/auth/status", { credentials: "include" })
      .then((r) => r.ok ? r.json() : null)
      .then((s) => {
        if (s?.email) setAdminEmail(String(s.email).toLowerCase());
        setMeineId(Number(s?.user_id ?? 0));
        setAllowAccountCreate(Boolean(s?.permissions?.allow_account_create));
        setDarfUebernehmen(Boolean(s?.permissions?.keys?.includes(PERM.usersImpersonate)));
      });
  }, [t]);

  /** Takes over the account and lands on the start page as that person. */
  async function uebernehmen(user: AdminUser) {
    setUebernahmeFehler("");
    const res = await fetch(`/api/admin/users/${user.id}/impersonate`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) {
      const d = await res.json().catch(() => null);
      setUebernahmeFehler(d?.detail || t("impersonate.failed"));
      return;
    }
    clearAuthCache();
    // Hard nav so the server layout re-reads the swapped session cookie.
    window.location.assign("/workspace");
  }

  /** Asks when an account loses the flag, otherwise it switches directly. */
  function askDemo(user: AdminUser, value: boolean) {
    const bisher = users.find((u) => u.is_demo);
    const verliert = value ? bisher && bisher.id !== user.id : user.is_demo;
    if (verliert) {
      setDemoFrage({ user, wert: value });
      return;
    }
    changeDemo(user.id, value);
  }

  async function changeDemo(userId: number, value: boolean) {
    const res = await fetch(`/api/admin/users/${userId}/demo`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_demo: value }),
    });
    if (res.ok) {
      // There is only one demo account, ticking one unticks all the others.
      setUsers((prev) => prev.map((u) =>
        u.id === userId ? { ...u, is_demo: value } : value ? { ...u, is_demo: false } : u,
      ));
    }
  }

  async function changeRole(userId: number, value: string) {
    const opt = roleOptions.find((o) => o.value === value);
    if (!opt) return;
    const role = opt.value.startsWith("custom:") ? "custom" : opt.value;
    const customRoleId = opt.customId;
    const res = await fetch(`/api/admin/users/${userId}/role`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, custom_role_id: customRoleId }),
    });
    if (res.ok) {
      setUsers((prev) => prev.map((u) =>
        u.id === userId
          ? { ...u, role: role as AdminUser["role"], custom_role_id: customRoleId }
          : u,
      ));
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("users.searchPlaceholder")}
          className="flex-1 min-w-50 text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb"
        />
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          title={t("users.from")}
          className="text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb"
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          title={t("users.to")}
          className="text-sm border border-border rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-kb"
        />
        <Select
          value={String(limit)}
          onChange={(v) => setLimit(Number(v))}
          options={pageSizeOptions}
          className="w-40"
        />
        <span className="text-xs text-muted-soft whitespace-nowrap">{t("users.totalUsers", { n: total })}</span>
        {allowAccountCreate && (
          <button
            type="button"
            onClick={() => setShowCreateDialog(true)}
            className="px-3 py-2 text-sm btn-primary rounded-md transition-colors whitespace-nowrap"
          >
            {t("createAccount.buttonLabel")}
          </button>
        )}
      </div>

      {uebernahmeFehler && (
        <StatusMark tone="error" className="text-sm">
          {uebernahmeFehler}
        </StatusMark>
      )}

      {loading ? (
        <Spinner className="flex justify-center py-12" />
      ) : users.length === 0 ? (
        <EmptyState
          size="lg"
          icon={<Users size={32} weight="bold" />}
          text={t("users.empty")}
        />
      ) : (
        // Relative keeps absolute children like sr-only labels inside, otherwise they widen the page.
        <div className="relative overflow-x-auto">
          <table className="w-full text-sm border border-border-soft rounded-xl overflow-hidden">
            <thead className="bg-surface text-xs text-muted uppercase">
              <tr>
                <th className="px-4 py-3 text-left">{t("users.colName")}</th>
                <th className="px-4 py-3 text-left">{t("users.colEmail")}</th>
                <th className="px-4 py-3 text-left">{t("users.colStatus")}</th>
                <th className="px-4 py-3 text-left">{t("roles.userRoleLabel")}</th>
                <th className="px-4 py-3 text-left" title={t("users.demoHint")}>{t("users.colDemo")}</th>
                <th className="px-4 py-3 text-left">{t("users.colCreated")}</th>
                <th className="px-4 py-3 text-left">{t("users.colActions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-soft bg-background">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-foreground">{u.display_name}</p>
                    <p className="text-xs text-muted-soft">{u.username}</p>
                  </td>
                  <td className="px-4 py-3 text-foreground-soft">
                    {u.email ?? <span className="text-border">-</span>}
                  </td>
                  <td className="px-4 py-3">
                    {u.active ? (
                      <StatusMark tone="success" className="text-xs">
                        {t("users.active")}
                      </StatusMark>
                    ) : (
                      <StatusMark tone="error" className="text-xs">
                        {t("users.inactive")}
                      </StatusMark>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {(() => {
                      const isEnvAdmin = !!u.email && u.email.toLowerCase() === adminEmail;
                      const currentValue =
                        u.role === "custom" && u.custom_role_id != null
                          ? `custom:${u.custom_role_id}`
                          : (u.role ?? "user");
                      if (isEnvAdmin) {
                        return (
                          <span
                            className="text-xs"
                            style={{ color: "var(--muted-soft)" }}
                            title={t("roles.envAdminLocked")}
                          >
                            {t("roles.roleAdmin")}
                          </span>
                        );
                      }
                      return (
                        <select
                          value={currentValue}
                          onChange={(e) => changeRole(u.id, e.target.value)}
                          className="text-xs border border-border rounded-md px-2 py-1 bg-background"
                        >
                          {roleOptions.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-3">
                    <Checkbox
                      checked={!!u.is_demo}
                      onChange={(v) => askDemo(u, v)}
                      label={t("users.colDemo")}
                      labelClassName="sr-only"
                    />
                  </td>
                  <td className="px-4 py-3 text-muted-soft text-xs whitespace-nowrap">
                    {formatDate(u.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <IconButton
                        size="sm"
                        title={t("users.quotaButtonTitle", { name: u.display_name })}
                        aria-label={t("users.quotaButtonTitle", { name: u.display_name })}
                        onClick={() => onOpenQuota(u.id)}
                      >
                        <Gauge size={14} weight="bold" />
                      </IconButton>
                      {darfUebernehmen &&
                        canImpersonate(u, { userId: meineId, adminEmail, gesperrteRollen }) && (
                          <IconButton
                            size="sm"
                            title={t("impersonate.buttonTitle", { name: u.display_name })}
                            aria-label={t("impersonate.buttonTitle", { name: u.display_name })}
                            onClick={() => uebernehmen(u)}
                          >
                            <SignIn size={14} weight="bold" />
                          </IconButton>
                        )}
                      {u.can_reset_link && (
                        <IconButton
                          size="sm"
                          title={t("users.resetLink.buttonTitle", { name: u.display_name })}
                          aria-label={t("users.resetLink.buttonTitle", { name: u.display_name })}
                          onClick={() => setResetFuer(u)}
                        >
                          <Key size={14} weight="bold" />
                        </IconButton>
                      )}
                      {canDeleteUser(u, { userId: meineId, email: adminEmail }) && (
                        <IconButton
                          size="sm"
                          title={t("users.delete.buttonTitle")}
                          aria-label={t("users.delete.buttonTitle")}
                          onClick={() => setZuLoeschen(u)}
                        >
                          <Trash size={14} weight="bold" />
                        </IconButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pager total={total} limit={limit} offset={offset} onOffset={setOffset} />

      {demoFrage && (
        <DemoConfirmDialog
          verlierer={(demoFrage.wert
            ? users.find((u) => u.is_demo)?.display_name
            : demoFrage.user.display_name) ?? ""}
          wechsel={demoFrage.wert}
          onCancel={() => setDemoFrage(null)}
          onConfirm={async () => {
            await changeDemo(demoFrage.user.id, demoFrage.wert);
            setDemoFrage(null);
          }}
        />
      )}

      {resetFuer && (
        <ResetLinkDialog
          userId={resetFuer.id}
          userName={resetFuer.display_name || resetFuer.username}
          onClose={() => setResetFuer(null)}
        />
      )}

      {zuLoeschen && (
        <DeleteUserConfirmDialog
          userId={zuLoeschen.id}
          userName={zuLoeschen.display_name || zuLoeschen.username}
          onCancel={() => setZuLoeschen(null)}
          onDeleted={() => {
            setZuLoeschen(null);
            setRefreshKey((k) => k + 1);
          }}
        />
      )}

      {showCreateDialog && (
        <CreateAccountDialog onClose={() => {
          setShowCreateDialog(false);
          setRefreshKey((k) => k + 1);
        }} />
      )}
    </div>
  );
}
