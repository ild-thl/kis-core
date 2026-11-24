/** The field takes a whole link or a bare code, the backend only takes the code. */
import { describe, expect, it } from "vitest";

import { extractJoinCode } from "./joinInput";

describe("extractJoinCode", () => {
  it("liest den Code aus einem ganzen Link", () => {
    expect(extractJoinCode("https://kis.example.org/?code=7f3a91c2")).toBe("7f3a91c2");
  });

  it("liest den Code auch mit Sprachpfad und weiteren Parametern", () => {
    expect(extractJoinCode("https://kis.example.org/de/?code=7f3a91c2&utm=mail")).toBe(
      "7f3a91c2",
    );
  });

  it("liest den Code aus dem Link zur Modulliste", () => {
    expect(extractJoinCode("https://kis.example.org/workspace?code=7f3a91c2")).toBe("7f3a91c2");
  });

  it("kommt ohne Schema aus", () => {
    expect(extractJoinCode("kis.example.org/?code=7f3a91c2")).toBe("7f3a91c2");
  });

  it("nimmt den nackten Code", () => {
    expect(extractJoinCode("7f3a91c2")).toBe("7f3a91c2");
  });

  it("schreibt klein, weil die Abfrage genau vergleicht", () => {
    expect(extractJoinCode("7F3A91C2")).toBe("7f3a91c2");
  });

  it("wirft Leerzeichen weg, auch mitten im Code", () => {
    expect(extractJoinCode("  7f3a 91c2  ")).toBe("7f3a91c2");
  });

  it("gibt null bei einem Satz statt eines Codes", () => {
    expect(extractJoinCode("Hallo, hier ist der Link")).toBeNull();
  });

  it("gibt null bei einer Adresse ohne Code", () => {
    expect(extractJoinCode("https://kis.example.org/workspace/abc")).toBeNull();
  });

  it("gibt null bei leerer Eingabe", () => {
    expect(extractJoinCode("   ")).toBeNull();
  });
});
