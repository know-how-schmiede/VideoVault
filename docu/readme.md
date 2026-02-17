# VideoVault

VideoVault is a desktop app built with Python and `customtkinter` to manage videos across multiple directories.

## Current Version

- `0.6.4`

## Features

- Manage multiple source directories
- Show the current number of configured source directories
- Import and export the directory list (`.json` or `.txt`) with a custom export filename
- Recursive scan for video files (`.mp4`, `.mkv`, `.avi`, `.mov`)
- Duplicate detection by filename, or optionally by parent directory name, each optionally combined with file size
- Visible progress bar while scanning
- Detail view with all found paths per video
- Clickable paths in the detail view to open videos in the default player
- Per-path action to open the parent folder in the file manager (`Open folder`)
- Movie metadata section below details with local description (`.nfo`/`.txt` sidecar files) and cover image (`poster/folder/cover` images)
- Download movie metadata from TMDB directly in the app (`Download from internet`)
- In-app TMDB API key form (`Set TMDB key`) with local persistence
- Local persistence in `videovault_data.json`
- Background scanning via `threading` to keep the UI responsive

## Internet Metadata Download

- Provider: TMDB API
- API key setup:
  - In-app: button `Set TMDB key` (saved locally in `videovault_data.json`)
  - Alternatively via environment variable: `TMDB_API_KEY`
- Download target location (recommended and implemented): directly next to the movie file in the movie folder
  - Description: `movie.nfo`
  - Cover: `poster.jpg`

Example (PowerShell):

```powershell
$env:TMDB_API_KEY = "your_tmdb_api_key"
python src/main.py
```

## Theme Notes (Light/Dark)

- The app UI itself (frames, lists, scrollbars, progress bar) switches between light and dark mode using `customtkinter`.
- The native Windows title bar is also switched to light/dark on supported systems.
- Info, warning, error, and yes/no dialogs are custom `CTkToplevel` dialogs and follow the selected theme.
- File dialogs (`tkinter.filedialog`) are still native system dialogs and cannot be fully styled like `customtkinter`.
- Depending on your Windows version and system settings, some file dialogs may look brighter than the app.
- For a fully uniform dark look, a custom in-app file browser would be required.

## Requirements

- Windows with PowerShell
- Python 3.13+ (recommended)

## Installation

1. Create a virtual environment:
   ```powershell
   python -m venv .venv
   ```
2. Activate the virtual environment:
   ```powershell
   & .\.venv\Scripts\Activate.ps1
   ```
3. If execution policy blocks activation:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   & .\.venv\Scripts\Activate.ps1
   ```
4. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```

## Run the App

```powershell
python src/main.py
```

## Build EXE (Optional)

```powershell
pyinstaller --onefile --windowed --name VideoVault src/main.py
```

## Project Files

- `src/main.py`: GUI and application logic
- `src/version.py`: Central version and app-name definitions
- `docu/version.md`: Version history
- `requirements.txt`: Python dependencies
