# Versionen

Dieses Dokument beschreibt die veroeffentlichten Versionen von VideoVault.

## Changelog

| Version | Datum       | Beschreibung |
|---------|-------------|--------------|
| 0.6.0   | 2026-02-17  | Doku erweitert und neue Funktionen zusammengefuehrt: pro Treffer in `Found paths` kann jetzt der uebergeordnete Ordner direkt im Dateimanager geoeffnet werden (`Open folder`). Metadaten/Cover koennen per TMDB-Download geladen werden, inklusive In-App-Formular zum Setzen des API-Keys (`Set TMDB key`) mit lokaler Speicherung. |
| 0.5.2   | 2026-02-17  | Im Bereich `Found paths` wurde pro Eintrag eine zusaetzliche Option zum Oeffnen des uebergeordneten Ordners im Dateimanager hinzugefuegt (`Open folder`). Zusaetzlich kann die App Metadaten und Cover direkt aus dem Internet (TMDB) laden und im Filmordner als `movie.nfo` und `poster.jpg` speichern. Der TMDB-API-Key kann nun direkt ueber ein Eingabe-Formular in der App gesetzt und lokal gespeichert werden. |
| 0.5.1   | 2026-02-17  | GUI-Sprache auf Englisch umgestellt (Labels, Statusmeldungen, Dialoge und Hinweistexte) sowie README auf Englisch aktualisiert. |
| 0.5.0   | 2026-02-16  | Verbesserungen im Bereich `Quell-Verzeichnisse`: `Hinzufuegen`-Button entfernt (Hinzufuegen per Enter), Sicherheitsabfrage vor `Alle loeschen`, optimierter Startordner bei `Ordner waehlen` (uebergeordneter Ordner), Anzeige der Verzeichnisanzahl sowie Import/Export der Verzeichnisliste (Exportname frei waehlbar). Zusaetzlich Fortschrittsbalken waehrend des Scan-Vorgangs. |
| 0.4.0   | 2026-02-15  | Neue Option fuer die Duplikatsuche: Als Grundlage kann jetzt der Name des uebergeordneten Verzeichnisses verwendet werden (optional kombiniert mit Dateigroesse). Persistenz der neuen Option in der lokalen JSON-Datei. |
| 0.3.1   | 2026-02-15  | Bugfix fuer klickbare Pfade im Bereich `Details`: Link-Erkennung auf robustes Klick-/Hover-Handling umgestellt, sodass Videos zuverlaessig im verknuepften Standard-Player geoeffnet werden. |
| 0.3.0   | 2026-02-15  | Im Bereich `Details` sind die `Gefundenen Pfade` nun klickbar; ein Klick oeffnet das Video mit dem im Betriebssystem verknuepften Standard-Videoplayer. |
| 0.2.0   | 2026-02-15  | Statistikbereich unter `Details` hinzugefuegt (gefundene Videos, letzter Scan, gefundene Duplikate), Listeneintraege ohne Trefferzaehler und ohne Duplikat-Praefix, Duplikate nur noch rot markiert, Persistenz des letzten Scan-Zeitpunkts. |
| 0.1.0   | 2026-02-15  | Erstrelease mit GUI, Verzeichnisverwaltung, rekursivem Video-Scan, Duplikat-Markierung, Detailansicht und JSON-Persistenz. |

## Versionierung

- Format: `MAJOR.MINOR.PATCH`
- Die aktive Versionsnummer ist zentral in `src/version.py` als `APP_VERSION` gepflegt.
