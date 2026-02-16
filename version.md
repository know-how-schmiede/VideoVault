# Versionen

Dieses Dokument beschreibt die veroeffentlichten Versionen von VideoVault.

## Changelog

| Version | Datum       | Beschreibung |
|---------|-------------|--------------|
| 0.5.0   | 2026-02-16  | Verbesserungen im Bereich `Quell-Verzeichnisse`: `Hinzufuegen`-Button entfernt (Hinzufuegen per Enter), Sicherheitsabfrage vor `Alle loeschen`, optimierter Startordner bei `Ordner waehlen` (uebergeordneter Ordner), Anzeige der Verzeichnisanzahl sowie Import/Export der Verzeichnisliste (Exportname frei waehlbar). Zusaetzlich Fortschrittsbalken waehrend des Scan-Vorgangs. |
| 0.4.0   | 2026-02-15  | Neue Option fuer die Duplikatsuche: Als Grundlage kann jetzt der Name des uebergeordneten Verzeichnisses verwendet werden (optional kombiniert mit Dateigroesse). Persistenz der neuen Option in der lokalen JSON-Datei. |
| 0.3.1   | 2026-02-15  | Bugfix fuer klickbare Pfade im Bereich `Details`: Link-Erkennung auf robustes Klick-/Hover-Handling umgestellt, sodass Videos zuverlaessig im verknuepften Standard-Player geoeffnet werden. |
| 0.3.0   | 2026-02-15  | Im Bereich `Details` sind die `Gefundenen Pfade` nun klickbar; ein Klick oeffnet das Video mit dem im Betriebssystem verknuepften Standard-Videoplayer. |
| 0.2.0   | 2026-02-15  | Statistikbereich unter `Details` hinzugefuegt (gefundene Videos, letzter Scan, gefundene Duplikate), Listeneintraege ohne Trefferzaehler und ohne Duplikat-Praefix, Duplikate nur noch rot markiert, Persistenz des letzten Scan-Zeitpunkts. |
| 0.1.0   | 2026-02-15  | Erstrelease mit GUI, Verzeichnisverwaltung, rekursivem Video-Scan, Duplikat-Markierung, Detailansicht und JSON-Persistenz. |

## Versionierung

- Format: `MAJOR.MINOR.PATCH`
- Die aktive Versionsnummer ist zentral in `version.py` als `APP_VERSION` gepflegt.
