# Campus map

The campus map shows the campus of TH Lübeck as an interactive map. It sits at the end of every
page and can also be opened in its own tab.

## What it shows

- **Buildings and facilities**: a click opens photos, opening hours and further details.
- **Accessibility, bike stations and bus stops**: each can be shown separately via the map
  elements.
- **Exploring**: clicking through buildings and solving small quizzes unlocks badges, see the
  map's own menu.
- **Direct link**: an address with `?show=` opens the map straight at a given place, used for
  example by the info assistant for its place cards.

## Embedding the campus map

The campus map can be embedded on other pages too, as a stand-alone iframe. The map address is set
in the admin under Info assistant.

```html
<iframe
    src="https://s3.mylab.th-luebeck.de/mb00083805-campus-map/campus-map/index.html?lang=en"
    title="Campus map TH Lübeck"
    width="100%"
    height="700"
    style="border:0; display:block; max-width:100%;"
    loading="lazy"
    allowfullscreen
    allow="clipboard-write"
    referrerpolicy="no-referrer-when-downgrade">
</iframe>
```

Appended to the address, `?show=B.59` jumps straight to that building, `&lang=de` switches the
map to German.
