"use client";

import { useEffect, useState } from "react";
import PageView from "../_components/PageView";
import { LOOKS } from "../_components/looks";
import type { Look } from "../_components/looks/registry";
import { PageLang } from "../_components/looks/shared";
import type { Design, Page } from "../_lib/types";
import { LIMITS, SAMPLES, samplePage } from "./sample";
import echt from "./echt.json";
import "../_components/page.css";

const BASE = "/pages-vorschau";
const DESIGNS: Design[] = ["chapters", "timeline", "magazine", "guide"];

/** Temporary preview of every look and of whole sample pages, no login, sample data only. */
export default function Vorschau() {
  const [tab, setTab] = useState<"looks" | "echt" | Design>("looks");
  // ?seite=magazine opens a sample page directly, for screenshots.
  useEffect(() => {
    const d = new URLSearchParams(window.location.search).get("seite");
    if (d === "echt" || DESIGNS.includes(d as Design)) setTab(d as Design | "echt");
  }, []);
  let n = 0;
  return (
    <div>
      <div className="flex flex-wrap gap-2 px-6 pt-4">
        {(["looks", ...DESIGNS] as const).map((x) => (
          <button key={x} type="button" onClick={() => setTab(x)}
            className={`px-3 py-1 text-sm font-semibold rounded-lg border-2 transition-colors ${tab === x ? "border-kb" : "border-border hover:border-kb"}`}>
            {x === "looks" ? "Alle Varianten" : `Seite: ${x}`}
          </button>
        ))}
      </div>
      {tab === "looks" ? (
        <PageLang.Provider value="de">
          <div className="askf-page d-chapters">
            <main className="wrap">
              {SAMPLES.map((b, s) => {
                const all = (LOOKS[b.kind] as Look[] | undefined) ?? [];
                return all.map((look, k) => {
                  if (look.fits && !look.fits(b as never)) return null;
                  n++;
                  const View = look.View;
                  return (
                    <section key={`${s}-${k}`} id={`v${n}`} className="frame" style={{ paddingTop: 56 }}>
                      <p className="vs-head" style={{ fontSize: "0.9375rem", margin: "0 0 1.125rem", color: "var(--muted)" }}>
                        <b style={{ color: "var(--foreground)" }}>{n}</b> · {b.kind} · {look.name}
                      </p>
                      <div className={`blk k-${b.kind}`}>
                        <View b={b as never} p={`x.${s}`} limits={LIMITS} imageBase={BASE} num={1} />
                      </div>
                    </section>
                  );
                });
              })}
            </main>
          </div>
        </PageLang.Provider>
      ) : (
        <PageView key={tab} page={tab === "echt" ? (echt as unknown as Page) : samplePage(tab)} limits={LIMITS} imageBase={BASE} />
      )}
    </div>
  );
}
