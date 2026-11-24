import { describe, expect, it } from "vitest";
import { checkForm } from "./checkForm";

describe("checkForm", () => {
  it("laesst einen Code durch", () => {
    expect(checkForm({ code: "ASKF-4K2P-7RXM" })).toEqual({ ok: true });
  });

  it("verlangt einen Code", () => {
    expect(checkForm({ code: "  " })).toEqual({ ok: false, reason: "codeMissing" });
  });
});
