"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { driver, type Config, type Driver, type PopoverDOM } from "driver.js";
import { TOUR_STEPS } from "./steps";
import { demoSchritte, type DemoSchritt, type TourAktionen } from "./demoSteps";
import { merkeTourGesehen } from "./tourSeen";
import { knoepfeAngleichen, knoepfeWarten } from "@/components/tour/popoverStil";

/** Longest wait for a station's target, after that the step shows anyway. */
const ZIEL_HOECHSTENS_MS = 6000;
/** Shortest pause after a preparation, a fresh tab needs a frame or two to draw. */
const ZIEL_MINDESTENS_MS = 250;
const ZIEL_TAKT_MS = 100;
/** A click this soon after a jump is the tail of a double click, driver.js is still fading the new station in. */
const DOPPELKLICK_MS = 500;

interface StartOptionen {
  /** The demo course gets the long tour, it knows the files there. */
  demo?: boolean;
  aktionen?: TourAktionen;
  workspaceUuid?: string;
  /** Whoever may not create modules skips the owner stations, see demoSteps. */
  darfModuleAnlegen?: boolean;
}

/**
 * Drives the guided tour through the course.
 *
 * Two scripts: the short one for any course, and the long one for the demo
 * course, which opens materials and studio tabs itself (see demoSteps). Every
 * step can be left with "next", including the ones asking for an action, so
 * nobody gets stuck.
 */
export function useTour() {
  const t = useTranslations("workspace.detail.tour");
  const tAllgemein = useTranslations("common");
  const laufend = useRef<Driver | null>(null);

  // Leaving the page ends a running tour, its overlay would otherwise cover the next page.
  useEffect(() => () => {
    laufend.current?.destroy();
    laufend.current = null;
  }, []);

  const knoepfeAnpassen = useCallback(
    (popover: PopoverDOM) => knoepfeAngleichen(popover, tAllgemein("close")),
    [tAllgemein],
  );

  /** First PDF in the source list, the selection bar only exists on those. */
  const erstePdfZeile = useCallback((): HTMLElement | null => {
    const zeilen = Array.from(document.querySelectorAll<HTMLElement>('[data-tour="source-row"]'));
    return zeilen.find((z) => /\.pdf\b/i.test(z.textContent ?? "")) ?? null;
  }, []);

  const grundEinstellungen = useCallback((): Config => ({
    showProgress: true,
    allowClose: true,
    // A click beside the popover must not end the tour, the X and Escape do that.
    overlayClickBehavior: () => {},
    overlayOpacity: 0.6,
    // Half of the smallest cut-out, so the ring around a round button is round too.
    stageRadius: 24,
    nextBtnText: t("next"),
    prevBtnText: t("back"),
    doneBtnText: t("done"),
    progressText: t("progress", { current: "{{current}}", total: "{{total}}" }),
    popoverClass: "askf-tour",
    onPopoverRender: knoepfeAnpassen,
    // Only the last step counts as done, so breaking off keeps the invitation
    // on the start page. driver.js hands the last step to this hook instead of
    // onNextClick, and taking the hook means closing up afterwards ourselves.
    onDoneClick: (_element, _schritt, opts) => {
      void merkeTourGesehen(true);
      opts.driver.destroy();
    },
    onDestroyed: () => {
      laufend.current = null;
    },
  }), [t, knoepfeAnpassen]);

  const startAllgemein = useCallback(() => {
    const vorhanden = TOUR_STEPS.filter((s) => {
      if (document.querySelector(`[data-tour="${s.anchor}"]`)) return true;
      // Its anchor appears only once an earlier step opened it.
      return s.opensOnDemand === true && erstePdfZeile() !== null;
    });
    if (vorhanden.length === 0) return;

    let fuehrung: Driver;
    fuehrung = driver({
      ...grundEinstellungen(),
      steps: vorhanden.map((s, i) => ({
        element: `[data-tour="${s.anchor}"]`,
        popover: {
          title: t(`steps.${s.key}.title`),
          description: t(`steps.${s.key}.text`),
          side: s.side,
          align: "start" as const,
          // The tour opens the PDF itself, so the selection bar step never
          // drops out just because nobody clicked a source beforehand. The key
          // is only set where it is needed: driver.js takes its presence as
          // "you handle next yourself", even when the value is undefined.
          ...(vorhanden[i + 1]?.opensOnDemand
            ? {
                onNextClick: () => {
                  knoepfeWarten(fuehrung.getState("popover") as PopoverDOM | undefined, "next");
                  erstePdfZeile()?.click();
                  window.setTimeout(() => fuehrung.moveNext(), 600);
                },
              }
            : {}),
        },
      })),
    });

    laufend.current = fuehrung;
    fuehrung.drive();
  }, [t, erstePdfZeile, grundEinstellungen]);

  const startDemo = useCallback(async (
    aktionen: TourAktionen,
    workspaceUuid?: string,
    darfModuleAnlegen = true,
  ) => {
    // The examples live per person and no early station needs them, so the
    // tour starts right away and fetches them once they exist.
    if (workspaceUuid) {
      fetch("/api/ai-assistant/demo/tour-content", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_uuid: workspaceUuid }),
      })
        .then(() => aktionen.beispieleLaden())
        .catch(() => { /* The tour runs without the examples too. */ });
    }

    const schritte = demoSchritte(darfModuleAnlegen);
    const ziel = (s: DemoSchritt) => (s.ziel ? (() => s.ziel!() ?? undefined) : undefined);

    let fuehrung: Driver;
    // One jump at a time, a second click while a station still loads would skip the next one.
    let unterwegs = false;
    let letzterSprung = 0;
    /** Prepares a station and moves on once its target stands on the page, capped so a missing anchor never stalls the tour. */
    const springe = (
      s: DemoSchritt | undefined,
      weiter: () => void,
      richtung: "next" | "prev" = "next",
    ) => {
      if (unterwegs || Date.now() - letzterSprung < DOPPELKLICK_MS) return;
      const los = () => { letzterSprung = Date.now(); unterwegs = false; weiter(); };
      if (!s || (!s.vorbereiten && !s.ziel)) { los(); return; }
      unterwegs = true;
      // The station takes its time, so the clicked button says so until it stands.
      knoepfeWarten(fuehrung.getState("popover") as PopoverDOM | undefined, richtung);
      s.vorbereiten?.(aktionen);
      const start = Date.now();
      const pruefen = () => {
        const el = s.ziel?.() ?? null;
        const gewartet = Date.now() - start;
        const bereit = !s.ziel || el !== null;
        if ((bereit && gewartet >= (s.vorbereiten ? ZIEL_MINDESTENS_MS : 0)) || gewartet >= ZIEL_HOECHSTENS_MS) {
          // driver.js scrolls only when the target leaves the viewport, a row deep
          // in its list needs this so the popover has room beside it.
          el?.scrollIntoView({ block: "center", inline: "nearest" });
          los();
          return;
        }
        window.setTimeout(pruefen, ZIEL_TAKT_MS);
      };
      pruefen();
    };

    // Whoever closed the tour while a station was still preparing gets no late jump.
    const solangeAktiv = (weiter: () => void) => () => { if (fuehrung.isActive()) weiter(); };
    fuehrung = driver({
      ...grundEinstellungen(),
      steps: schritte.map((s, i) => ({
        element: ziel(s) as unknown as () => Element,
        popover: {
          title: t(`demo.${s.key}.title`),
          description: t(`demo.${s.key}.text`),
          side: s.side,
          align: "start" as const,
          // Each step opens what it points at, so the hook belongs to the step
          // being entered and not to the one being left. driver.js reads the
          // presence of the key as "you handle it yourself", so the last step
          // keeps none and its "done" still reaches onDoneClick.
          ...(i + 1 < schritte.length
            ? { onNextClick: () => springe(schritte[i + 1], solangeAktiv(() => fuehrung.moveNext())) }
            : {}),
          ...(i > 0
            ? { onPrevClick: () => springe(schritte[i - 1], solangeAktiv(() => fuehrung.movePrevious()), "prev") }
            : {}),
        },
      })),
    });

    laufend.current = fuehrung;
    springe(schritte[0], () => fuehrung.drive());
    // The start is no jump, the first click must not fall into the double click window.
    letzterSprung = 0;
  }, [t, grundEinstellungen]);

  const start = useCallback((optionen?: StartOptionen) => {
    if (optionen?.demo && optionen.aktionen) {
      void startDemo(optionen.aktionen, optionen.workspaceUuid, optionen.darfModuleAnlegen);
      return;
    }
    startAllgemein();
  }, [startAllgemein, startDemo]);

  return { start };
}
