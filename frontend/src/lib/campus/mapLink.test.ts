import { describe, expect, it } from "vitest";
import { mapFile, mapLink } from "./mapLink";

describe("mapLink", () => {
  it("carries the language and keeps the path", () => {
    expect(mapLink("https://map.test/campus-map/", "en")).toBe("https://map.test/campus-map/?lang=en");
  });
  it("adds the place and encodes it", () => {
    expect(mapLink("https://map.test/campus-map/", "de", "MFC 8")).toBe("https://map.test/campus-map/?lang=de&show=MFC+8");
  });
  it("adds the partner and its two links", () => {
    expect(mapLink("https://map.test/", "de", undefined, { home: "https://k.test/", back: "https://k.test/services" })).toBe(
      "https://map.test/?lang=de&partner=kis&home=https%3A%2F%2Fk.test%2F&back=https%3A%2F%2Fk.test%2Fservices",
    );
  });
  it("turns off the intro zoom for the modal", () => {
    expect(mapLink("https://map.test/", "de", undefined, undefined, true)).toBe("https://map.test/?lang=de&intro=0");
  });
  it("replaces a language already in the link", () => {
    expect(mapLink("https://map.test/?lang=de", "en")).toBe("https://map.test/?lang=en");
  });
  it("returns a broken setting unchanged instead of throwing", () => {
    expect(mapLink("campus-map", "de")).toBe("campus-map");
  });
});

describe("mapFile", () => {
  it("finds files next to an index.html", () => {
    expect(mapFile("https://s3.test/b/campus-map/index.html?lang=de", "preview.jpg")).toBe("https://s3.test/b/campus-map/preview.jpg");
  });
  it("treats an address without slash as a folder", () => {
    expect(mapFile("https://map.test/campus-map", "preview.jpg")).toBe("https://map.test/campus-map/preview.jpg");
    expect(mapFile("https://map.test/campus-map/", "preview.jpg")).toBe("https://map.test/campus-map/preview.jpg");
  });
  it("returns nothing for a broken setting", () => {
    expect(mapFile("campus-map", "preview.jpg")).toBe("");
  });
});
