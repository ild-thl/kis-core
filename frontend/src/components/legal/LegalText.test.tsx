import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { LegalMarkdown } from "./LegalText";
import { legalText } from "@/lib/legal";

const html = (text: string) => renderToStaticMarkup(<LegalMarkdown text={text} />);

describe("LegalMarkdown", () => {
  it("shows raw HTML as harmless text instead of running it", () => {
    const out = html('Text <script>alert(1)</script> <img src=x onerror="alert(1)"> Ende');
    expect(out).not.toContain("<script");
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;script&gt;");
  });

  it("strips javascript links", () => {
    const out = html("[klick](javascript:alert(1)) [mail](mailto:a@example.org)");
    expect(out).not.toContain("javascript:");
    expect(out).toContain('href="mailto:a@example.org"');
  });

  it("keeps an address as plain text, there is no autolink", () => {
    expect(html("E-Mail: a@example.org")).not.toContain("<a");
  });

  it("keeps line breaks inside a paragraph for the address block", () => {
    const out = html("Name\nStraße 1");
    expect(out).toContain("whitespace-pre-line");
    expect(out).toContain("Name\nStraße 1");
  });

  it("renders headings with the old page classes", () => {
    expect(html("## 1. Verantwortlicher")).toContain('<h2 class="text-lg font-semibold mt-6 mb-2">1. Verantwortlicher</h2>');
    expect(html("### Kontakt:")).toContain('<p class="font-semibold text-foreground-soft mt-4 mb-2">Kontakt:</p>');
  });
});

describe("legalText", () => {
  it("falls back to German while English is empty", () => {
    expect(legalText({ de: "Impressum", en: "" }, "en")).toBe("Impressum");
    expect(legalText({ de: "Impressum", en: "  " }, "en")).toBe("Impressum");
    expect(legalText({ de: "Impressum", en: "Imprint" }, "en")).toBe("Imprint");
    expect(legalText({ de: "Impressum", en: "Imprint" }, "de")).toBe("Impressum");
  });

  it("is empty without any text, so the page shows its notice", () => {
    expect(legalText({ de: " ", en: "" }, "de")).toBe("");
  });
});
