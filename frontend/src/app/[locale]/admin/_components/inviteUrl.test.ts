/** The link is built in the browser from the page address. */
import { describe, expect, it } from "vitest";

import { inviteUrl } from "./inviteUrl";

describe("inviteUrl", () => {
  it("haengt den Schluessel an die Einladungsseite", () => {
    expect(inviteUrl("https://kis.example.org", "7Kq2xR")).toBe(
      "https://kis.example.org/invite/7Kq2xR",
    );
  });

  it("erzeugt keinen doppelten Schraegstrich", () => {
    expect(inviteUrl("http://localhost:3000/", "7Kq2xR")).toBe(
      "http://localhost:3000/invite/7Kq2xR",
    );
  });
});
