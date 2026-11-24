# System

Settings for the whole platform, spread over three tabs.

## Operation

- **Maintenance mode**: on means everyone without the right Access during maintenance gets a
  maintenance page instead of the app. Needed, for example, before reindexing the materials.
- **Start page notice**: a text shown as a bar above the menu, for everyone, expandable, collapsed
  it only shows the word Notice. Links in the text are written as [label](address). An empty field
  means the notice stays hidden even with the switch on.
- **Welcome window on first login**: a text shown to every account exactly once, right after its
  very first login, never again after that. Seeing it additionally needs a right of its own in the
  rights matrix.

## Legal

- **Imprint and privacy policy**: one text each in German and English, in Markdown. Without the
  English text, the German one is shown. Without any text, the page only shows a notice.
- **Contact email**: shown at sign-in, on the activation page and on the start page. Left empty,
  the contact links disappear.

## Campus map

The address of the map page. The map is hosted outside the platform, the place list for the info
assistant and the footer preview image sit next to it. An empty field or the switch set to off
means no map, no footer tile and no place cards in the info assistant. How to embed the map on
other pages is described in the article Campus map.
