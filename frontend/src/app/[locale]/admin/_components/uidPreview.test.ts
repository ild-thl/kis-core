/** The preview has to match what the backend makes of the same entry. */
import { describe, expect, it } from "vitest";

import { uidPreview } from "./uidPreview";

describe("uidPreview", () => {
  it("laesst einen fertigen Benutzernamen stehen", () => {
    expect(uidPreview("max.mustermann")).toBe("max.mustermann");
  });

  it("macht aus Grossbuchstaben und Umlauten kleine Buchstaben", () => {
    expect(uidPreview("Jörg.Müller")).toBe("joerg.mueller");
  });

  it("verbindet einen ausgeschriebenen Namen mit einem Strich", () => {
    expect(uidPreview("Anna Beispiel")).toBe("anna-beispiel");
  });

  it("wirft weg was ein Anmeldename nicht annimmt", () => {
    expect(uidPreview("anna+test")).toBe("annatest");
  });

  it("kuerzt auf die Hoechstlaenge", () => {
    expect(uidPreview("a".repeat(40))).toHaveLength(32);
  });
});
