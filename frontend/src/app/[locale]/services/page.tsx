"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import LockedNotice from "@/components/auth/LockedNotice";
import { checkAuthStatus } from "@/lib/auth";
import { EMPTY_PERMS, PERM, hasPerm } from "@/lib/permissions";
import { homeTargets, enabledToolKeys, type HomeTarget } from "@/lib/modules";
import { useEnabledTools } from "@/hooks/useEnabledTools";
import { stampCardState, usePublicEvent } from "@/lib/event/usePublicEvent";
import type { AuthStatus } from "@/types";
import StartOverview from "../_components/StartOverview";
import WelcomeModal from "../workspace/_components/WelcomeModal";

interface HomeState {
  targets: HomeTarget[];
  stamp: "open" | "upcoming" | null;
}

export default function HomePage() {
  return (
    <ProtectedRoute>
      {/* The query string is only readable inside a Suspense boundary. */}
      <Suspense>
        <HomeRouter />
      </Suspense>
    </ProtectedRoute>
  );
}

/** With the learning assistant this is the services page, without it the home page, a single place to go is a straight redirect. */
function HomeRouter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const { loaded: toolsLoaded, tools: enabledTools } = useEnabledTools();
  const { data: event, failed: eventFailed } = usePublicEvent();
  const [state, setState] = useState<HomeState | null>(null);

  useEffect(() => {
    checkAuthStatus().then(setAuth);
  }, []);

  useEffect(() => {
    if (!auth || !toolsLoaded || (!event && !eventFailed)) return;
    const perms = auth.permissions ?? EMPTY_PERMS;
    setState({
      targets: homeTargets(auth.modules, perms, enabledToolKeys(enabledTools)),
      stamp: stampCardState(event),
    });
  }, [auth, toolsLoaded, enabledTools, event, eventFailed]);

  const code = searchParams.get("code");
  const hasAia = state?.targets.some((z) => z.kind === "aia") ?? false;
  const tools = state?.targets.filter((z) => z.kind === "tool") ?? [];
  // Old invitation links still point here, the enrolment card lives on the module list, which is also home for everyone without a service.
  const weiter =
    state === null
      ? null
      : hasAia && code
        ? `/workspace?code=${encodeURIComponent(code)}`
        : hasAia && tools.length === 0
          ? "/workspace"
          : !hasAia && tools.length === 1 && !state.stamp
            ? tools[0].href
            : null;

  useEffect(() => {
    if (weiter) router.replace(weiter);
  }, [weiter, router]);

  if (state === null || weiter) return null;

  return (
    <>
      {/* The module list greets everyone with the assistant, impersonation shows the target account's own view. */}
      {!hasAia && !auth?.impersonator && hasPerm(auth?.permissions, PERM.generalWelcome) && (
        <WelcomeModal userId={auth?.user_id} />
      )}
      {tools.length === 0 && !state.stamp ? (
        <div className="px-4 sm:px-6 md:px-8 pt-10 pb-20">
          <div className="max-w-2xl mx-auto">
            <LockedNotice variant="aia" />
          </div>
        </div>
      ) : (
        <StartOverview
          targets={tools}
          home={!hasAia}
          stamp={hasAia ? null : state.stamp}
          stampFrom={event?.stamp?.availableFrom ?? ""}
          stampTitle={event?.stamp?.title}
          stampBody={event?.stamp?.body}
        />
      )}
    </>
  );
}
