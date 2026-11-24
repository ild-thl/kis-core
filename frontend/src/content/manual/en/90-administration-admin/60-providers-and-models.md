# Providers and models

Under Providers & models sit the accesses to the AI providers and the question which function
uses which model, in two tabs.

## Providers

A provider needs a name, a protocol, an address, and usually a key. After saving, askFrancis shows only
the last six characters of the key. Concurrent calls can be capped per area, and for a voice
provider, voices can be loaded automatically or entered by hand. Per row: enable, check
reachability, edit, delete, plus export/import and delete everything in the menu.

## Functions

Each function (chat, image analysis, image generation, OCR, speech recognition, text-to-speech,
translation, ...) shows every eligible provider with its own model field, in an order that the
arrows change.

- **Standard**: the topmost provider with an entered model. For text-to-speech it also sets the
  default voice.
- **The next one steps in** when the standard does not answer, refuses, or is full for the LLM,
  then the one after it. Images do not shift when a provider is full. For text-to-speech only the
  second one takes over, at the start and for the whole job, the voice never switches midway.
- When a provider is disabled or deleted, the next one in the order moves up.
- For some functions the person chooses the provider in the service themselves, likewise for
  podcast, presentation, and report, where the standard is only the default and the list follows
  the order.
- Per row, a test of the current selection. Every change applies immediately for everyone, there
  is no preview and no test mode.
