/** Max upload size for general documents (translate, summary, image). */
export const MAX_UPLOAD_MB = 500;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

/** Max upload size for audio/video transcription. */
export const MAX_TRANSCRIPTION_MB = 500;
export const MAX_TRANSCRIPTION_BYTES = MAX_TRANSCRIPTION_MB * 1024 * 1024;

/** Longest playing time for transcription, checked in the browser instead of after the upload. */
export const MAX_TRANSCRIPTION_MINUTES = 100;

/** Max upload size for images (image edit/analyze). */
const MAX_IMAGE_MB = 20;
export const MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024;

/** Max script chars for screencast (mirrors backend SCREENCAST_MAX_CHARS in limits.py). */
export const SCREENCAST_MAX_CHARS = 100_000;

/** Max chars for direct text-to-speech input (mirrors backend TTS_MAX_CHARS in limits.py). */
export const TTS_MAX_CHARS = 100_000;

/** Max chars for direct translate text input (mirrors backend TRANSLATE_MAX_CHARS in limits.py). */
export const TRANSLATE_MAX_CHARS = 100_000;

/** UI locales for the header language switch (next-intl). */
export const UI_LOCALES = ["de", "en"] as const;
export const DEFAULT_UI_LOCALE: (typeof UI_LOCALES)[number] = "de";

/** Translate-tool language codes (DeepL format). Mirrors backend TRANSLATE_LANGUAGES in i18n.py. */
export const TRANSLATE_LANGUAGES = ["DE", "EN-US"] as const;
export const DEFAULT_TRANSLATE_TARGET: (typeof TRANSLATE_LANGUAGES)[number] = "EN-US";
/** Screencast: only these languages the voice speaks cleanly, measured at the provider. */
export const SCREENCAST_TARGET_LANGUAGES = ["DE", "EN-US"] as const;

/** Custom event so the header settings menu can re-show a dismissed HomeNotice. */
export const HOME_NOTICE_SHOW_EVENT = "askf:home-notice-show";

/** AI Act transparency notice embedded in generated files, always bilingual regardless of viewer locale. Mirrors backend AI_HINWEIS_TEXT in ai_hinweis.py. */
export const AI_HINWEIS_TEXT = "Diese Datei wurde mithilfe von KI erstellt. This file was created with AI assistance.";

/** Typed-in text is saved under this name by translation and TTS, a real upload never is. */
export const TEXT_MODE_FILENAME = "text.txt";
