/** The export keeps only the chosen providers and tidies the routes to match. */
import { describe, expect, it } from "vitest";

import { filterExportConfig } from "./_exportFilter";

function exportMit(route: Record<string, unknown>) {
  return {
    schema_version: 1,
    providers: [{ name: "Lokal" }, { name: "myLab" }],
    feature_routes: [
      {
        feature: "chat",
        provider_name: "Lokal",
        model_name: "gemma",
        user_choices: [],
        provider_models: { Lokal: "gemma", myLab: "qwen" },
        ...route,
      },
    ],
  };
}

type Gefiltert = { feature_routes: Array<Record<string, unknown>> };

describe("filterExportConfig", () => {
  it("behaelt den Rueckfall, wenn sein Anbieter mitkommt", () => {
    const out = filterExportConfig(exportMit({ fallback_provider_name: "myLab" }), new Set(["Lokal", "myLab"]));
    expect((out as Gefiltert).feature_routes[0].fallback_provider_name).toBe("myLab");
  });

  it("leert den Rueckfall, wenn sein Anbieter nicht mitkommt", () => {
    const out = filterExportConfig(exportMit({ fallback_provider_name: "myLab" }), new Set(["Lokal"]));
    const r = (out as Gefiltert).feature_routes[0];
    expect(r.fallback_provider_name).toBeNull();
    expect(r.provider_models).toEqual({ Lokal: "gemma" });
  });

  it("behaelt eine Stimmen-Route, die nur einen Rueckfall hat", () => {
    const route = { feature: "tts", provider_name: null, fallback_provider_name: "myLab" };
    const out = filterExportConfig(exportMit(route), new Set(["myLab"]));
    const r = (out as Gefiltert).feature_routes[0];
    expect(r.fallback_provider_name).toBe("myLab");
    expect(r.provider_models).toEqual({ myLab: "qwen" });
  });

  it("laesst eine Stimmen-Route ohne Erstwahl fallen, wenn ihr Rueckfall nicht mitkommt", () => {
    const route = { feature: "tts", provider_name: null, fallback_provider_name: "myLab" };
    const out = filterExportConfig(exportMit(route), new Set(["Lokal"]));
    expect((out as Gefiltert).feature_routes).toEqual([]);
  });

  it("laesst eine andere Route ohne Erstwahl weiter fallen", () => {
    const route = { provider_name: null, fallback_provider_name: "myLab" };
    const out = filterExportConfig(exportMit(route), new Set(["Lokal", "myLab"]));
    expect((out as Gefiltert).feature_routes).toEqual([]);
  });

  it("fuegt kein Feld hinzu, das der Export nicht hatte", () => {
    const out = filterExportConfig(exportMit({}), new Set(["Lokal"]));
    expect("fallback_provider_name" in (out as Gefiltert).feature_routes[0]).toBe(false);
  });
});
