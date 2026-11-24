# Die Dienste im Überblick

Die Startseite zeigt jeden Dienst als Kachel mit einem Satz dazu, was er tut. Die Gruppe trägt die
Marke Lehrende, sie richtet sich an Lehrende.

![Die Startseite mit den Kacheln](/manual/{lang}/start-page.png)

- **Übersetzung** übersetzt Texte und Dokumente zwischen Deutsch und Englisch und behält das Layout
- **Text in Audio** liest Texte und Dokumente vor
- **Audio in Text** schreibt Audio und Video mit
- **Report** führt mehrere Materialien zu einem Text zusammen
- **Pages** macht aus Material eine Lernseite, die Sie ändern und teilen können
- **Screencast** macht aus Folien ein vertontes Video
- **Podcast** macht aus Material ein Gespräch zum Anhören
- **Präsentation** macht aus Material eine PowerPoint-Datei im Design der Hochschule
- **Bildgenerierung** erzeugt, bearbeitet und beschreibt Bilder
- **Dolmetscher** übersetzt ein Gespräch zwischen zwei Sprachen live mit
- **Glossar** pflegt Begriffslisten für Übersetzungen

Wer nur ein einziges Ziel hat, etwa Studierende mit dem Lernassistenten allein, landet direkt dort
und sieht die Kachelseite nicht. Zurück zur Startseite führt immer das askFrancis-Logo oben links.

## Wer welche Dienste sieht

Jeder Dienst ist ein eigenes Recht in der Rechtematrix, benannt wie seine Kachel. Dazu kann die
Verwaltung jeden Dienst für alle freigeben oder sperren. Fehlt eine Kachel, liegt es an einem von
beiden.

## Dateien oder Workspace

Die meisten Dienste arbeiten mit einer hochgeladenen Datei: hinein, Ergebnis, herunterladen.
Report, Podcast, Präsentation und das Zusatzmaterial des Screencasts haben daneben einen
Reiter Workspace. Dort wählen Sie fertig verarbeitete Materialien aus einem Ihrer Workspaces, ohne
sie noch einmal hochzuladen. Der Reiter erscheint nur, wenn Sie den Lernassistenten nutzen dürfen.

## Aufträge und Kontingent

Lange Aufträge laufen im Hintergrund. Sie können die Seite verlassen, das Ergebnis wartet unter
**Jobs** in der Kopfleiste.

- **Kontingent**: ab Werk 100 Aufträge je Dienst in 4 Stunden. Die Präsentation hat keins.
  Dolmetscher und Glossar erzeugen keine Aufträge und zählen nirgends mit.
- **Offene Aufträge**: höchstens 5 zugleich je Person. Dienste mit Stimme, also Text in Audio,
  Podcast und Screencast, zählen getrennt von den übrigen, eine laufende Vertonung blockiert also
  keine Übersetzung. Darüber meldet der Dienst: Du hast gerade zu viele Aufträge laufen. Warte,
  bis einer fertig ist.
- **Beide Zahlen** ändert die Verwaltung unter Grenzen.

## Material für Report, Podcast und Präsentation

Die drei Dienste und das Zusatzmaterial des Screencasts nehmen dasselbe Material mit denselben
Grenzen:

- **Umfang**: bis zu 10 Dateien oder Workspace-Materialien je Auftrag, als PDF, Word, PowerPoint,
  Text oder Markdown. Der Report nimmt auch Untertitel als SRT und VTT.
- **Je Datei**: 500 MB und 200 Seiten, beides stellt die Verwaltung ein.
- **Zusammen**: 500.000 Zeichen über alle Dateien, fest im Code. Ein Zähler auf der Seite zeigt
  beim Auswählen, wie viel davon verbraucht ist. Ist es zu viel, bleibt der Start gesperrt, bis
  Sie etwas herausnehmen.
- **Textebene**: Gelesen wird nur Text. Gescannte Seiten ohne Text bleiben leer, eine Datei ohne
  jeden Text wird abgelehnt.

## Die optionale Anweisung

Report, Podcast und Präsentation haben ein Feld Anweisung. Es bleibt leer, wenn Sie
nichts Besonderes wollen. Die KI liest die Anweisung neben dem Material und ordnet sie ein:

- **Ein Thema** engt ein: Nur Kapitel 2 plant alles um das, was das Material dazu sagt, und lässt
  den Rest weg, auch ganze Dateien.
- **Ein Wunsch zur Art** formt nur den Text: für Erstsemester, kurz, mit Beispielen. Der Inhalt
  bleibt der des Materials, nichts kommt dazu.
- **Ein Thema, das im Material fehlt**, fällt weg. Podcast und Präsentation sagen das mit einem
  Hinweis und nutzen das ganze Material, der Report tut es stillschweigend.
- **Unsinn** oder die Bitte, das Material zu verlassen, fällt still weg.

Nach 500 Zeichen wird die Anweisung abgeschnitten.

## Hinweis auf KI in den Ergebnissen

Was die Dienste erzeugen, trägt einen Hinweis, dass es mit KI entstanden ist, soweit das Format
das zulässt:

- **MP3** aus Text in Audio und Podcast: in den Dateiinformationen, beim Anhören merkt man nichts
- **Video** aus dem Screencast: eine Hinweisfolie am Anfang und am Ende
- **Bilder**: in den Bildinformationen der PNG-Datei
- **Untertitel als VTT**: eine Notizzeile, die kein Player anzeigt
- **Report**: eine Zeile unter dem Titel, in Markdown wie in Word
- **Präsentation**: KI generiert unten rechts auf jeder Folie

Übersetzte Dokumente, Untertitel als SRT, das Transkript eines Podcasts und das Protokoll des
Dolmetschers bleiben ohne Hinweis.
