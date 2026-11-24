import type { APIRequestContext } from "@playwright/test";

/**
 * Sets the demo account and hands back a function that restores the state.
 *
 * Necessary because only ONE account can be the demo account: whoever sets the
 * flag takes it away from whoever had it. Without restoring, every test run
 * would silently wipe the demo course out of the local dev environment, and the
 * module list, the tour card and the tour menu entry go with it.
 */
export async function demoKontoUebernehmen(
  admin: APIRequestContext,
  username: string,
): Promise<() => Promise<void>> {
  const liste = await (await admin.get("/api/admin/users?limit=100")).json();
  const vorher = liste.users.find((u: { is_demo?: boolean }) => u.is_demo);
  const konto = liste.users.find((u: { username: string }) => u.username === username);
  await admin.post(`/api/admin/users/${konto.id}/demo`, { data: { is_demo: true } });
  return async () => {
    await admin.post(`/api/admin/users/${konto.id}/demo`, { data: { is_demo: false } });
    if (vorher && vorher.id !== konto.id) {
      await admin.post(`/api/admin/users/${vorher.id}/demo`, { data: { is_demo: true } });
    }
  };
}
