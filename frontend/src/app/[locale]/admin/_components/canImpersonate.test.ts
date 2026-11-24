/** The button never appears where the server would refuse. */
import { describe, expect, it } from "vitest";

import { canImpersonate, gesperrteRollenIds } from "./canImpersonate";
import { PERM } from "@/lib/permissions";

const ICH = { userId: 1, adminEmail: "admin@example.org", gesperrteRollen: [5] };

describe("canImpersonate", () => {
  it("bietet ein normales Konto an", () => {
    expect(canImpersonate({ id: 7, email: "studi@example.org", role: "user", active: 1 }, ICH)).toBe(true);
  });

  it("bietet Lehrende an", () => {
    expect(canImpersonate({ id: 7, role: "staff", active: 1 }, ICH)).toBe(true);
  });

  it("bietet das eigene Konto nicht an", () => {
    expect(canImpersonate({ id: 1, role: "admin", active: 1 }, ICH)).toBe(false);
  });

  it("bietet ein Admin-Konto nicht an", () => {
    expect(canImpersonate({ id: 9, role: "admin", active: 1 }, ICH)).toBe(false);
  });

  it("erkennt das Konto aus der Konfiguration an der Mailadresse", () => {
    expect(canImpersonate({ id: 9, email: "Admin@Example.org", role: "user", active: 1 }, ICH)).toBe(false);
  });

  it("bietet ein gesperrtes Konto nicht an", () => {
    expect(canImpersonate({ id: 7, role: "user", active: 0 }, ICH)).toBe(false);
  });

  it("bietet eine eigene Rolle mit Nutzerverwaltung nicht an", () => {
    expect(canImpersonate({ id: 7, role: "custom", custom_role_id: 5, active: 1 }, ICH)).toBe(false);
  });

  it("bietet eine harmlose eigene Rolle an", () => {
    expect(canImpersonate({ id: 7, role: "custom", custom_role_id: 6, active: 1 }, ICH)).toBe(true);
  });
});

describe("gesperrteRollenIds", () => {
  it("findet die Rollen mit Nutzerverwaltung", () => {
    const rollen = [
      { id: 5, permissions: [PERM.usersAll] },
      { id: 6, permissions: [PERM.statsUsers] },
      { id: 7, permissions: [PERM.usersImpersonate] },
      { id: 8 },
    ];
    expect(gesperrteRollenIds(rollen)).toEqual([5, 7]);
  });
});
