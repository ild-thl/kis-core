# i18n Messages

askFrancis uses [`next-intl`](https://next-intl.dev) for German/English UI translations. German is the default locale, English is opt-in via the header language switch or by visiting `/en/...`.

## Files

- `de.json` — German translations (source of truth, always populated first)
- `en.json` — English translations (must mirror `de.json` keys exactly)

Both files use nested JSON. Key paths follow the convention `featureArea.subArea.purpose`, e.g. `header.logout`, `jobs.filterBar.allTools`.

## Adding a new string

When you add any user-facing text to the UI:

1. Decide on a key under the right namespace (`header`, `footer`, `jobs`, `tools`, `admin`, `glossary`, `workspace`, `errors`, ...).
2. Add the key to **both** `de.json` AND `en.json` in the same commit. Skipping one breaks `npm run check:i18n`.
3. In the component, replace the hardcoded string with `t("namespace.key")` from `useTranslations("namespace")`.

```tsx
// Before
<button>Abbrechen</button>

// After
const t = useTranslations("modal");
<button>{t("cancel")}</button>
```

## ICU Syntax (plurals, dates, numbers)

Use ICU MessageFormat for variants. `next-intl` parses ICU automatically.

```json
{
  "jobs": {
    "count": "{count, plural, =0 {Keine Jobs} =1 {Ein Job} other {# Jobs}}"
  }
}
```

```tsx
t("count", { count: jobs.length });
```

## Verification

```bash
npm run check:i18n
```

Exits non-zero if `de.json` and `en.json` have mismatched key sets.

## Splitting

Single files per locale are fine while they stay below ~500 lines. Once a file gets too big, split per feature:

```
messages/
  de.json
  en.json
  de/
    workspace.json
    admin.json
  en/
    workspace.json
    admin.json
```

The corresponding loader change goes in `src/i18n/request.ts`.

## Backend coordination

User-facing strings produced by the FastAPI backend (HTTPException details, job status texts, tool labels) are translated server-side using `Accept-Language`. See `backend/src/i18n.py` for the helper.

LLM output language is controlled separately via the `target_language` parameter ("German" / "English"); the system prompts themselves remain in English. See `backend/src/tool_prompts.py`.
