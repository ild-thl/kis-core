"use client";

import { Suspense, useEffect, useState } from "react";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import { checkAuthStatus } from "@/lib/auth";
import { EMPTY_PERMS, PERM, hasPerm } from "@/lib/permissions";
import type { AuthStatus } from "@/types";
import WorkspaceHome from "./_components/WorkspaceHome";
import WelcomeModal from "./_components/WelcomeModal";

/** The module list, where everyone with the learning assistant lands after the login. */
export default function WorkspaceListPage() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);

  useEffect(() => {
    checkAuthStatus().then(setAuth);
  }, []);

  const perms = auth?.permissions ?? EMPTY_PERMS;

  return (
    <ProtectedRoute>
      {/* Impersonation shows the target account's own view, not an onboarding dialog for the admin's session. */}
      {auth && !auth.impersonator && hasPerm(perms, PERM.generalWelcome) && <WelcomeModal userId={auth.user_id} />}
      {auth && (
        <Suspense>
          <WorkspaceHome
            canCreate={!!perms.allow_workspace_create}
            languageInvite={hasPerm(perms, PERM.aiaLanguageLevel)}
          />
        </Suspense>
      )}
    </ProtectedRoute>
  );
}
