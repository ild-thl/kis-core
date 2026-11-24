import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit tests for pure frontend logic. Scoped to src/ so the Playwright E2E
// specs under e2e/ are NOT picked up (those run via `npm run test:e2e`).
export default defineConfig({
  // Mirrors the "@/*" path in tsconfig.json. Without it a tested module cannot
  // reach a shared helper under src/lib the way the app does.
  // Same JSX runtime as Next, so a component renders in a test without importing React.
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    // next-intl liefert ESM aus, das "next/navigation" ohne Dateiendung
    // importiert. Node loest das nur auf, wenn Vite das Paket mit uebersetzt.
    server: { deps: { inline: [/next-intl/] } },
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      // v8 instrumentation (no Babel), matches the vitest 2.x line.
      provider: "v8",
      // `all: true` counts every source file, not just the ones a test
      // imports, so the number reflects the whole codebase honestly. Most of
      // src/ is UI without unit tests, so expect a low baseline.
      all: true,
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/**/types.ts",
        "src/**/_types.ts",
      ],
      // text-summary keeps the CI log short; json-summary feeds the CI job
      // summary; html/json land as artifacts.
      reporter: ["text-summary", "json", "json-summary", "html"],
    },
  },
});
