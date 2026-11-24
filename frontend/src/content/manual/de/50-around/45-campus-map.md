# Campusplan

Der Campusplan zeigt den Campus der TH Lübeck als interaktive Karte. Er steht am Ende jeder Seite
und lässt sich auch in einem eigenen Tab öffnen.

## Was er zeigt

- **Gebäude und Einrichtungen**: ein Klick öffnet Fotos, Öffnungszeiten und weitere Angaben.
- **Barrierefreiheit, Fahrradstationen und Bushaltestellen**: einzeln über die Kartenelemente
  einblendbar.
- **Erkundung**: wer Gebäude anklickt und kleine Quizze löst, schaltet Badges frei, nachzusehen
  im Menü der Karte.
- **Direktlink**: eine Adresse mit `?show=` öffnet die Karte gleich an einem bestimmten Ort,
  genutzt zum Beispiel vom Infoassistenten für seine Ortskarten.

## Campusplan einbinden

Der Campusplan lässt sich auch auf anderen Seiten einbinden, als eigenständiges iframe. Die Adresse
der Karte steht im Admin unter Infoassistent.

```html
<iframe
    src="https://s3.mylab.th-luebeck.de/mb00083805-campus-map/campus-map/index.html?lang=de"
    title="Campusplan TH Lübeck"
    width="100%"
    height="700"
    style="border:0; display:block; max-width:100%;"
    loading="lazy"
    allowfullscreen
    allow="clipboard-write"
    referrerpolicy="no-referrer-when-downgrade">
</iframe>
```

An die Adresse angehängt springt `?show=B.59` gleich zu diesem Gebäude, `&lang=en` stellt die
Karte auf Englisch.
