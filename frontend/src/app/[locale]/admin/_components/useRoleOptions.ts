import { useEffect, useMemo, useState } from "react";

type CustomRole = { id: number; name: string };

/** The roles an admin dialog offers: staff, user and every custom role. */
export function useRoleOptions(staffLabel: string, userLabel: string) {
  const [customRoles, setCustomRoles] = useState<CustomRole[]>([]);

  useEffect(() => {
    fetch("/api/admin/roles", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.custom_roles) setCustomRoles(d.custom_roles);
      })
      .catch(() => {});
  }, []);

  return useMemo(
    () => [
      { value: "staff", label: staffLabel },
      { value: "user", label: userLabel },
      ...customRoles.map((r) => ({ value: `custom:${r.id}`, label: r.name })),
    ],
    [staffLabel, userLabel, customRoles],
  );
}

/** Splits a select value like "custom:7" into the two fields the backend expects. */
export function roleToPayload(role: string): { askf_role: string; custom_role_id: number | null } {
  const custom = role.startsWith("custom:");
  return {
    askf_role: custom ? "custom" : role,
    custom_role_id: custom ? Number(role.slice("custom:".length)) : null,
  };
}
