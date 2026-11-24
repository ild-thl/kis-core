// House styling for the scrollbars and buttons inside the sandboxed viewer.
const PDF_SHADOW_CSS = `
          :host *::-webkit-scrollbar { width: 5px !important; height: 5px !important; }
          :host *::-webkit-scrollbar-track { background: transparent !important; }
          :host *::-webkit-scrollbar-thumb { background: #d8d8d8 !important; border-radius: 999px !important; }
          :host *::-webkit-scrollbar-thumb:hover { background: #bbb !important; }
          :host * { scrollbar-width: thin !important; scrollbar-color: #d8d8d8 transparent !important; }
          /** outline instead of border, that shifts nothing and keeps the tab underline. */
          :host button,
          :host [role="button"],
          :host [class*="command-button"],
          :host [class*="-button"] {
            outline: 2px solid transparent !important;
            outline-offset: 0 !important;
          }
          :host button:hover,
          :host button:focus-visible,
          :host [role="button"]:hover,
          :host [role="button"]:focus-visible,
          :host [class*="command-button"]:hover,
          :host [class*="command-button"]:focus-visible,
          :host [class*="-button"]:hover,
          :host [class*="-button"]:focus-visible {
            outline-color: var(--kb) !important;
            /* Suppress EmbedPDFs hover ring (Tailwind ring + box-shadow) so only our outline shows */
            box-shadow: none !important;
            --tw-ring-shadow: 0 0 transparent !important;
            --tw-ring-offset-shadow: 0 0 transparent !important;
          }
          /* Mode tabs: inactive ones get rounded + hover outline; bottom border off */
          :host [data-epdf-i="mode-tabs"] button {
            border-radius: 6px !important;
            border-bottom: 0 !important;
          }
          /* Active mode tab: only bottom strich (no outline, no radius, no hover effect) */
          :host [data-epdf-i="mode-tabs"] button[class*="text-accent"],
          :host [data-epdf-i="mode-tabs"] button[class*="text-accent"]:hover,
          :host [data-epdf-i="mode-tabs"] button[class*="text-accent"]:focus-visible {
            outline: none !important;
            border-bottom: 2px solid var(--kb) !important;
            border-radius: 0 !important;
          }
        `;

/** Adds the style once, false while the shadow root is not there yet. */
export function injectShadowStyle(container: HTMLElement | null): boolean {
  const shadow = container?.querySelector("embedpdf-container")?.shadowRoot;
  if (!shadow || shadow.querySelector("[data-askf-scrollbar]")) return false;
  const style = document.createElement("style");
  style.setAttribute("data-askf-scrollbar", "");
  style.textContent = PDF_SHADOW_CSS;
  shadow.appendChild(style);
  return true;
}
