/** The map link in the viewer's language, optionally jumping straight to one place. */
export function mapLink(mapUrl: string, locale: string, show?: string, partner?: { home: string; back: string }, noIntro?: boolean): string {
  let url: URL;
  try {
    url = new URL(mapUrl);
  } catch {
    return mapUrl;
  }
  url.searchParams.set("lang", locale);
  if (show) url.searchParams.set("show", show);
  if (partner) {
    url.searchParams.set("partner", "kis");
    url.searchParams.set("home", partner.home);
    url.searchParams.set("back", partner.back);
  }
  // The modal is a quick glance, the intro zoom only fits the full page in its own tab.
  if (noIntro) url.searchParams.set("intro", "0");
  return url.toString();
}

/** A file the map keeps next to its page, such as its preview image. */
export function mapFile(mapUrl: string, name: string): string {
  try {
    const url = new URL(mapUrl);
    url.search = "";
    url.hash = "";
    const last = url.pathname.split("/").pop() ?? "";
    if (last && !last.includes(".")) url.pathname += "/";
    return new URL(name, url).toString();
  } catch {
    return "";
  }
}
