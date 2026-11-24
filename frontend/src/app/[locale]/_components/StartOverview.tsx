"use client";

import { useTranslations } from "next-intl";
import type { HomeTarget } from "@/lib/modules";
import { TOOL_ICONS } from "@/lib/toolIcons";
import { Greeting } from "@/app/[locale]/workspace/_components/Greeting";
import { EvaluationInvite } from "@/app/[locale]/workspace/_components/EvaluationInvite";
import { useEventTasks, useTaskCardMinimized } from "@/lib/event/tasks";
import { TaskCard, TaskGiftButton } from "@/components/event/TaskCard";
import type { Text2 } from "@/lib/event/types";
import { StartTile } from "./StartTile";
import { StampButton } from "./StampButton";

type ToolTarget = Extract<HomeTarget, { kind: "tool" }>;

/** The services page, and the home page with greeting and event cards for accounts without the learning assistant. */
export default function StartOverview({
  firstName,
  targets,
  home,
  stamp = null,
  stampFrom = "",
  stampTitle,
  stampBody,
}: {
  firstName: string;
  targets: HomeTarget[];
  /** Without the learning assistant this page is where the login lands. */
  home: boolean;
  stamp?: "open" | "upcoming" | null;
  stampFrom?: string;
  stampTitle?: Text2;
  stampBody?: Text2;
}) {
  const t = useTranslations("startOverview");
  const tasks = useEventTasks();
  const [tasksMin, setTasksMin] = useTaskCardMinimized();
  const tools = targets.filter((z): z is ToolTarget => z.kind === "tool");
  // The info assistant only visits here until it moves to the university website, so it comes last.
  const ordered = [...tools.filter((z) => z.key !== "campus"), ...tools.filter((z) => z.key === "campus")];
  const showTasks = home && tasks.visible;
  const headingClass = "text-sm font-semibold uppercase tracking-wider";
  // Equal rows keep every tile as tall as the tallest one.
  const gridClass = "grid auto-rows-fr gap-4 sm:grid-cols-2 lg:grid-cols-3";

  return (
    <div className="page-shell pt-6 pb-20 lg:pt-15 lg:pb-30">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col gap-8" data-testid="start-overview">
          {home && (
            <div className={gridClass}>
              {/* The greeting row spans the page so the folded task card, or else the stamp card, sits at its right end. */}
              <div className="sm:col-span-2 lg:col-span-3 flex items-start justify-between gap-4">
                <Greeting firstName={firstName} />
                {showTasks && tasksMin && <TaskGiftButton done={tasks.done} onOpen={() => setTasksMin(false)} />}
                {stamp && !showTasks && <StampButton stamp={stamp} from={stampFrom} title={stampTitle} body={stampBody} />}
              </div>
              <div className="flex flex-col md:flex-row gap-4 empty:hidden sm:col-span-2 lg:col-span-3">
                {showTasks && !tasksMin && (
                  <TaskCard
                    done={tasks.done}
                    workspace={tasks.workspace}
                    workspaceTitle={tasks.workspaceTitle}
                    onMinimize={() => setTasksMin(true)}
                  />
                )}
                <EvaluationInvite />
              </div>
            </div>
          )}

          {ordered.length > 0 && (
            <section className="flex flex-col gap-2">
              {/* Reached from the header button, the group heading is the page title in the style of the workspace list. */}
              {home ? (
                <h2 className={headingClass}>{t("groups.tools")}</h2>
              ) : (
                <h1 className="text-xl md:text-2xl font-bold mb-4">{t("groups.tools")}</h1>
              )}
              <div className={gridClass}>
                {ordered.map((z) => (
                  <StartTile
                    key={z.key}
                    href={z.href}
                    icon={TOOL_ICONS[z.key]}
                    title={t(`tools.${z.key}.title`)}
                    body={t(`tools.${z.key}.body`)}
                    testId={`start-tile-${z.key}`}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
