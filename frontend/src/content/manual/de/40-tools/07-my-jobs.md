# Meine Jobs

Jeder Auftrag an einen Dienst ist ein Job. Die Jobliste zeigt, was läuft, was fertig ist und was
schiefging.

![Die Jobliste](/manual/{lang}/my-jobs.png)

## Wo sie steht

Über **Jobs** in der Kopfleiste. Der rote Punkt daneben heißt: Seit Sie die Liste zuletzt
geöffnet haben, ist ein Auftrag fertig geworden oder gescheitert.

## Was Sie dort tun

- **Filtern** nach Dienst, Zeitraum oder Suchbegriff.
- **Herunterladen**: das Ergebnis, bei einem Report zusätzlich die Word-Datei. Hat ein
  Auftrag mehrere Quellen, klappt die Dateiliste unter dem Namen auf.
- **Öffnen**: Podcast, Präsentation und Screencast führen zurück in ihren Dienst, ein
  unterbrochener Screencast lässt sich von dort fortsetzen.
- **Wiederholen** oder löschen, was gescheitert ist.

## Zustände

- **Wartend** und **In der Warteschlange**: der Auftrag ist angenommen und noch nicht dran
- **Läuft**: es wird gearbeitet
- **Neuer Anlauf**: der Auftrag wartet kurz und versucht es von selbst wieder
- **Angehalten**: nach mehreren gescheiterten Anläufen wartet der Auftrag auf **Weiter**
- **Fortsetzen**: der Auftrag wartet auf eine Eingabe von Ihnen, etwa beim Screencast
- **Fertig**, **Fehler** und **Abgelaufen**: bei Abgelaufen war der Auftrag fertig, die
  Ergebnisdatei ist aber nicht mehr da

## Was bei einem Fehler passiert

Lange Aufträge arbeiten in Etappen und sichern Zwischenstände. Scheitert ein Stück, macht askFrancis von
selbst bis zu 3 neue Anläufe, nach 1 Minute, 3 Minuten und 10 Minuten. Danach steht der Auftrag auf
Angehalten und nennt den letzten Fehler. Weiter setzt dort an, wo es aufgehört hat, fertige Teile
bleiben.

Ein überlasteter KI-Anbieter zählt nicht als Fehler. Der Auftrag wartet 1 bis 3 Minuten und
versucht es erneut, bis zu 12 Stunden lang, ohne dass ein Anlauf verbraucht wird.

Das gilt für Text in Audio, Report, Screencast, Podcast und Präsentation. Beim Podcast
und der Präsentation behalten nur Vertonung und Folienbau ihre fertigen Teile, Skript und
Gliederung beginnen bei einem Fehler von vorn. Übersetzung, Audio in Text und Bildgenerierung
kennen kein Anhalten, dort steht gleich Fehler und Sie wiederholen.

Ein Auftrag, der 7 Tage angehalten oder wartend liegt, wird aufgegeben.

## Die Liste ist begrenzt

Ab Werk bleiben die letzten 100 Jobs je Person. Kommt ein neuer dazu, fällt der älteste heraus,
mitsamt Ergebnis. Eine Frist gibt es nicht. Die Verwaltung kann die Zahl ändern, auch auf
unbegrenzt.
