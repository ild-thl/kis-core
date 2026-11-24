import { describe, expect, it } from "vitest";
import { resetUrl } from "./resetUrl";

describe("resetUrl", () => {
  it("joins origin and token", () => {
    expect(resetUrl("https://askfrancis.example/", "abc")).toBe("https://askfrancis.example/reset-password/abc");
  });
});
