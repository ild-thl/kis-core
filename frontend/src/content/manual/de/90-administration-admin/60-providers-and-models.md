# Anbieter und Modelle

Unter Anbieter & Modelle liegen die Zugänge zu den KI-Anbietern und die Frage, welche Funktion
welches Modell nutzt, in zwei Reitern.

## Anbieter

Ein Anbieter braucht einen Namen, ein Protokoll, eine Adresse und meist einen Schlüssel. Nach dem
Speichern zeigt askFrancis nur noch die letzten sechs Zeichen des Schlüssels. Dazu lässt sich die Zahl
gleichzeitiger Aufrufe je Bereich begrenzen, und bei einem Stimmanbieter die Stimmen laden oder
von Hand eintragen. Je Zeile: aktivieren, Erreichbarkeit prüfen, bearbeiten, löschen, dazu
Export/Import und Alles löschen im Menü.

## Funktionen

Jede Funktion (Chat, Bildanalyse, Bildgenerierung, Texterkennung, Spracherkennung,
Text-to-Speech, Übersetzung, ...) zeigt alle passenden Anbieter mit eigenem Modellfeld, in einer
Reihenfolge, die sich mit den Pfeilen ändern lässt.

- **Standard**: der oberste Anbieter mit eingetragenem Modell. Bei Text-to-Speech legt er
  zusätzlich die Standardstimme fest.
- **Der Nächste springt ein**, wenn der Standard nicht antwortet, ablehnt oder beim LLM voll ist,
  danach der Übernächste. Bilder weichen bei vollem Anbieter nicht aus. Bei Text-to-Speech
  übernimmt nur der Zweite, und zwar beim Start für den ganzen Auftrag, die Stimme wechselt nie
  mittendrin.
- Wird ein Anbieter abgeschaltet oder gelöscht, rückt der nächste in der Reihenfolge auf.
- Bei einigen Funktionen wählt die Person den Anbieter selbst im Dienst, bei Podcast,
  Präsentation und Report ebenso, der Standard ist dort nur die Vorgabe, die Liste folgt der
  Reihenfolge.
- Je Zeile ein Test der aktuellen Auswahl. Jede Änderung gilt sofort für alle, eine Vorschau oder
  einen Testbetrieb gibt es nicht.
