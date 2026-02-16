# VideoVault

VideoVault ist eine Desktop-App auf Basis von Python und `customtkinter`, um Videos aus mehreren Verzeichnissen zu verwalten.

## Funktionen

- Verwaltung mehrerer Quell-Verzeichnisse
- Anzeige der aktuellen Anzahl hinterlegter Quell-Verzeichnisse
- Import und Export der Verzeichnisliste (`.json` oder `.txt`), Exportname frei waehlbar
- Rekursiver Scan auf Video-Dateien (`.mp4`, `.mkv`, `.avi`, `.mov`)
- Duplikat-Erkennung nach Dateiname oder optional nach uebergeordnetem Verzeichnisnamen, jeweils optional kombiniert mit Dateigroesse
- Sichtbarer Fortschrittsbalken waehrend des Scan-Vorgangs
- Detailansicht mit allen gefundenen Pfaden pro Video
- Klickbare Pfade in der Detailansicht zum direkten Oeffnen im Standard-Videoplayer
- Lokale Persistenz in `videovault_data.json`
- Hintergrund-Scan mit `threading`, damit die GUI reaktionsfaehig bleibt

## Voraussetzungen

- Windows mit PowerShell
- Python 3.13+ (empfohlen)

## Installation

1. Virtuelle Umgebung erstellen:
   ```powershell
   python -m venv .venv
   ```
2. Virtuelle Umgebung aktivieren:
   ```powershell
   & .\.venv\Scripts\Activate.ps1
   ```
3. Falls Execution Policy blockt:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   & .\.venv\Scripts\Activate.ps1
   ```
4. Abhaengigkeiten installieren:
   ```powershell
   python -m pip install -r requirements.txt
   ```

## Anwendung starten

```powershell
python main.py
```

## EXE erstellen (optional)

```powershell
pyinstaller --onefile --windowed --name VideoVault main.py
```

## Projektrelevante Dateien

- `main.py`: GUI und Anwendungslogik
- `version.py`: Zentrale Versions- und Programmnamen-Definition
- `version.md`: Version-Historie
- `requirements.txt`: Python-Abhaengigkeiten
