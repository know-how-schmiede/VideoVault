from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import END, Listbox, SINGLE, filedialog

import customtkinter as ctk

from version import WINDOW_TITLE


@dataclass
class VideoEntry:
    name: str
    paths: list[str]
    sizes: list[int]
    is_duplicate: bool

    @classmethod
    def from_dict(cls, item: dict) -> "VideoEntry | None":
        name = item.get("name")
        paths = item.get("paths", [])
        sizes = item.get("sizes", [])
        is_duplicate = item.get("is_duplicate", False)

        if not isinstance(name, str) or not isinstance(paths, list):
            return None

        clean_paths = [p for p in paths if isinstance(p, str)]
        clean_sizes = [s for s in sizes if isinstance(s, int)]
        if len(clean_sizes) != len(clean_paths):
            clean_sizes = [0] * len(clean_paths)

        return cls(
            name=name,
            paths=clean_paths,
            sizes=clean_sizes,
            is_duplicate=bool(is_duplicate),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "paths": self.paths,
            "sizes": self.sizes,
            "is_duplicate": self.is_duplicate,
        }


class JsonStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def load(self) -> tuple[list[str], bool, bool, str | None, list[VideoEntry], str]:
        if not self.file_path.exists():
            return [], False, False, None, [], "System"

        try:
            with self.file_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return [], False, False, None, [], "System"

        raw_dirs = payload.get("directories", [])
        duplicate_by_size = bool(payload.get("duplicate_by_size", False))
        duplicate_by_parent_dir = bool(payload.get("duplicate_by_parent_dir", False))
        raw_last_scan_at = payload.get("last_scan_at")
        raw_videos = payload.get("videos", [])
        raw_appearance_mode = payload.get("appearance_mode", "System")
        last_scan_at = raw_last_scan_at if isinstance(raw_last_scan_at, str) else None
        appearance_mode = raw_appearance_mode if isinstance(raw_appearance_mode, str) else "System"

        directories = [item for item in raw_dirs if isinstance(item, str)]
        videos: list[VideoEntry] = []
        if isinstance(raw_videos, list):
            for item in raw_videos:
                if isinstance(item, dict):
                    entry = VideoEntry.from_dict(item)
                    if entry is not None:
                        videos.append(entry)

        return directories, duplicate_by_size, duplicate_by_parent_dir, last_scan_at, videos, appearance_mode

    def save(
        self,
        directories: list[str],
        duplicate_by_size: bool,
        duplicate_by_parent_dir: bool,
        last_scan_at: str | None,
        videos: list[VideoEntry],
        appearance_mode: str,
    ) -> None:
        payload = {
            "directories": directories,
            "duplicate_by_size": duplicate_by_size,
            "duplicate_by_parent_dir": duplicate_by_parent_dir,
            "last_scan_at": last_scan_at,
            "videos": [video.to_dict() for video in videos],
            "appearance_mode": appearance_mode,
        }
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except OSError:
            pass


class VideoScanner:
    VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov"}

    def scan(
        self, directories: list[str], duplicate_by_size: bool, duplicate_by_parent_dir: bool
    ) -> tuple[list[VideoEntry], list[str]]:
        grouped: dict[tuple[str, int | None], dict[str, object]] = {}
        warnings: list[str] = []
        seen_directories: set[str] = set()

        for raw_directory in directories:
            directory = os.path.abspath(os.path.normpath(raw_directory))
            normalized = os.path.normcase(directory)
            if normalized in seen_directories:
                continue
            seen_directories.add(normalized)

            if not os.path.isdir(directory):
                warnings.append(f"Verzeichnis nicht gefunden: {directory}")
                continue

            for root, _, files in os.walk(directory):
                for filename in files:
                    extension = Path(filename).suffix.lower()
                    if extension not in self.VIDEO_EXTENSIONS:
                        continue

                    full_path = os.path.join(root, filename)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        warnings.append(f"Datei nicht lesbar: {full_path}")
                        continue

                    if duplicate_by_parent_dir:
                        parent_dir_name = os.path.basename(root).strip().lower()
                        key_name = parent_dir_name if parent_dir_name else filename.lower()
                    else:
                        key_name = filename.lower()

                    key = (key_name, size if duplicate_by_size else None)
                    if key not in grouped:
                        grouped[key] = {"name": filename, "items": []}

                    cast_items = grouped[key]["items"]
                    if isinstance(cast_items, list):
                        cast_items.append((full_path, size))

        entries: list[VideoEntry] = []
        for group in grouped.values():
            name = group["name"] if isinstance(group["name"], str) else "Unbekannt"
            items = group["items"] if isinstance(group["items"], list) else []
            item_pairs = [
                (path, size)
                for path, size in items
                if isinstance(path, str) and isinstance(size, int)
            ]
            item_pairs.sort(key=lambda value: value[0].lower())

            paths = [path for path, _ in item_pairs]
            sizes = [size for _, size in item_pairs]
            if not paths:
                continue

            entries.append(
                VideoEntry(
                    name=name,
                    paths=paths,
                    sizes=sizes,
                    is_duplicate=len(paths) > 1,
                )
            )

        entries.sort(key=lambda value: (value.name.lower(), value.paths[0].lower()))
        return entries, warnings


class VideoVaultApp(ctk.CTk):
    DATA_FILE = "videovault_data.json"
    APPEARANCE_LABEL_TO_MODE = {
        "System": "System",
        "Hell": "Light",
        "Dunkel": "Dark",
    }
    APPEARANCE_MODE_TO_LABEL = {
        "System": "System",
        "Light": "Hell",
        "Dark": "Dunkel",
    }

    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("1200x760")
        self.minsize(980, 620)

        self.store = JsonStore(Path(__file__).resolve().parent / self.DATA_FILE)
        self.scanner = VideoScanner()

        self.video_entries: list[VideoEntry] = []
        self.row_to_entry: dict[int, VideoEntry] = {}
        self.is_scanning = False
        self.last_scan_at: str | None = None
        self.details_link_tags: dict[str, str] = {}

        self.duplicate_by_size_var = ctk.BooleanVar(value=False)
        self.duplicate_by_parent_dir_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="Bereit")
        self.stats_videos_var = ctk.StringVar(value="0")
        self.stats_last_scan_var = ctk.StringVar(value="Nie")
        self.stats_duplicates_var = ctk.StringVar(value="0")
        self.directory_count_var = ctk.StringVar(value="Anzahl: 0")
        self.appearance_mode = "System"
        self.appearance_mode_var = ctk.StringVar(value="System")
        self.browse_initial_dir: str | None = None

        self._build_layout()
        self._load_saved_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=2)
        self.grid_columnconfigure(2, weight=2)
        self.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(self)
        top_bar.grid(row=0, column=0, columnspan=3, padx=12, pady=(12, 8), sticky="ew")
        top_bar.grid_columnconfigure(0, weight=1)
        top_bar.grid_columnconfigure(1, weight=0)
        top_bar.grid_columnconfigure(2, weight=0)
        top_bar.grid_columnconfigure(3, weight=0)
        top_bar.grid_columnconfigure(4, weight=0)
        top_bar.grid_columnconfigure(5, weight=0)
        top_bar.grid_rowconfigure(1, weight=0)

        status_label = ctk.CTkLabel(top_bar, textvariable=self.status_var, anchor="w")
        status_label.grid(row=0, column=0, padx=(12, 8), pady=12, sticky="ew")

        self.duplicate_checkbox = ctk.CTkCheckBox(
            top_bar,
            text="Duplikat-Check mit Dateigroesse",
            variable=self.duplicate_by_size_var,
            onvalue=True,
            offvalue=False,
            command=self._on_duplicate_mode_changed,
        )
        self.duplicate_checkbox.grid(row=0, column=1, padx=8, pady=12, sticky="e")

        self.duplicate_parent_checkbox = ctk.CTkCheckBox(
            top_bar,
            text="Duplikat-Basis: uebergeordnetes Verzeichnis",
            variable=self.duplicate_by_parent_dir_var,
            onvalue=True,
            offvalue=False,
            command=self._on_duplicate_mode_changed,
        )
        self.duplicate_parent_checkbox.grid(row=0, column=2, padx=8, pady=12, sticky="e")

        ctk.CTkLabel(top_bar, text="Design").grid(row=0, column=3, padx=(8, 4), pady=12, sticky="e")
        self.appearance_menu = ctk.CTkOptionMenu(
            top_bar,
            values=list(self.APPEARANCE_LABEL_TO_MODE.keys()),
            variable=self.appearance_mode_var,
            command=self._on_appearance_mode_changed,
            width=120,
        )
        self.appearance_menu.grid(row=0, column=4, padx=(0, 8), pady=12, sticky="e")

        self.scan_button = ctk.CTkButton(
            top_bar,
            text="Scan",
            width=180,
            height=42,
            font=ctk.CTkFont(size=17, weight="bold"),
            command=self.start_scan,
        )
        self.scan_button.grid(row=0, column=5, padx=(8, 12), pady=12, sticky="e")

        self.scan_progress = ctk.CTkProgressBar(top_bar, mode="indeterminate")
        self.scan_progress.grid(row=1, column=0, columnspan=6, padx=12, pady=(0, 12), sticky="ew")
        self.scan_progress.grid_remove()

        self._build_sources_panel()
        self._build_video_panel()
        self._build_details_panel()

    def _build_sources_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=1, column=0, padx=(12, 8), pady=(0, 12), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Quell-Verzeichnisse").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, textvariable=self.directory_count_var).grid(row=0, column=1, sticky="e")

        self.directory_entry = ctk.CTkEntry(panel, placeholder_text="Pfad eingeben und Enter druecken")
        self.directory_entry.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        self.directory_entry.bind("<Return>", lambda _event: self._add_directory_from_entry())

        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        controls.grid_columnconfigure(0, weight=1)

        self.browse_button = ctk.CTkButton(
            controls, text="Ordner waehlen", command=self._browse_directory
        )
        self.browse_button.grid(row=0, column=0, sticky="ew")

        list_container = ctk.CTkFrame(panel)
        list_container.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="nsew")
        list_container.grid_columnconfigure(0, weight=1)
        list_container.grid_rowconfigure(0, weight=1)

        self.directory_listbox = Listbox(list_container, selectmode=SINGLE, exportselection=False)
        self.directory_listbox.grid(row=0, column=0, sticky="nsew")

        self.directory_scrollbar = ctk.CTkScrollbar(
            list_container, orientation="vertical", command=self.directory_listbox.yview
        )
        self.directory_scrollbar.grid(row=0, column=1, sticky="ns")
        self.directory_listbox.configure(yscrollcommand=self.directory_scrollbar.set)

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="ew")
        footer.grid_columnconfigure((0, 1), weight=1)

        self.remove_button = ctk.CTkButton(
            footer, text="Entfernen", command=self._remove_selected_directory
        )
        self.remove_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.clear_button = ctk.CTkButton(
            footer, text="Alle loeschen", command=self._clear_directories
        )
        self.clear_button.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.import_button = ctk.CTkButton(
            footer, text="Import", command=self._import_directories
        )
        self.import_button.grid(row=1, column=0, padx=(0, 4), pady=(8, 0), sticky="ew")

        self.export_button = ctk.CTkButton(
            footer, text="Export", command=self._export_directories
        )
        self.export_button.grid(row=1, column=1, padx=(4, 0), pady=(8, 0), sticky="ew")

        self._update_directory_count()

    def _build_video_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=1, column=1, padx=(0, 8), pady=(0, 12), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Gefundene Videos").grid(
            row=0, column=0, padx=12, pady=(12, 8), sticky="w"
        )

        list_container = ctk.CTkFrame(panel)
        list_container.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        list_container.grid_columnconfigure(0, weight=1)
        list_container.grid_rowconfigure(0, weight=1)

        self.video_listbox = Listbox(list_container, selectmode=SINGLE, exportselection=False)
        self.video_listbox.grid(row=0, column=0, sticky="nsew")
        self.video_listbox.bind("<<ListboxSelect>>", self._on_video_selected)

        self.video_scrollbar = ctk.CTkScrollbar(
            list_container, orientation="vertical", command=self.video_listbox.yview
        )
        self.video_scrollbar.grid(row=0, column=1, sticky="ns")
        self.video_listbox.configure(yscrollcommand=self.video_scrollbar.set)

    def _build_details_panel(self) -> None:
        panel = ctk.CTkFrame(self)
        panel.grid(row=1, column=2, padx=(0, 12), pady=(0, 12), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_rowconfigure(3, weight=0)

        ctk.CTkLabel(panel, text="Details").grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")

        self.details_box = ctk.CTkTextbox(panel, wrap="word")
        self.details_box.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="nsew")
        self.details_box.bind("<Button-1>", self._on_details_click, add="+")
        self.details_box.bind("<Motion>", self._on_details_hover, add="+")
        self.details_box.bind("<Leave>", self._on_details_leave, add="+")
        self.details_box.bind("<Key>", lambda _event: "break")
        self._set_details_text("Waehle ein Video, um die gefundenen Pfade anzuzeigen.")

        ctk.CTkLabel(panel, text="Statistik").grid(row=2, column=0, padx=12, pady=(0, 6), sticky="w")

        stats_frame = ctk.CTkFrame(panel)
        stats_frame.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        stats_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(stats_frame, text="Gefundene Videos:").grid(
            row=0, column=0, padx=10, pady=(10, 4), sticky="w"
        )
        ctk.CTkLabel(stats_frame, textvariable=self.stats_videos_var).grid(
            row=0, column=1, padx=10, pady=(10, 4), sticky="e"
        )
        ctk.CTkLabel(stats_frame, text="Letzter Scan:").grid(
            row=1, column=0, padx=10, pady=4, sticky="w"
        )
        ctk.CTkLabel(stats_frame, textvariable=self.stats_last_scan_var).grid(
            row=1, column=1, padx=10, pady=4, sticky="e"
        )
        ctk.CTkLabel(stats_frame, text="Gefundene Duplikate:").grid(
            row=2, column=0, padx=10, pady=(4, 10), sticky="w"
        )
        ctk.CTkLabel(stats_frame, textvariable=self.stats_duplicates_var).grid(
            row=2, column=1, padx=10, pady=(4, 10), sticky="e"
        )

    def _load_saved_state(self) -> None:
        (
            directories,
            duplicate_by_size,
            duplicate_by_parent_dir,
            last_scan_at,
            videos,
            appearance_mode,
        ) = self.store.load()
        self.duplicate_by_size_var.set(duplicate_by_size)
        self.duplicate_by_parent_dir_var.set(duplicate_by_parent_dir)
        self.last_scan_at = last_scan_at
        self._set_appearance_mode(appearance_mode, save=False)

        for directory in directories:
            self._add_directory(directory, must_exist=False, save=False)

        self.video_entries = videos
        self._refresh_video_list()
        if videos:
            total_files = sum(len(item.paths) for item in videos)
            self.status_var.set(f"{len(videos)} Gruppen / {total_files} Dateien geladen")

    def _on_close(self) -> None:
        self._save_state()
        self.destroy()

    def _get_directories(self) -> list[str]:
        return [self.directory_listbox.get(index) for index in range(self.directory_listbox.size())]

    def _center_dialog(self, dialog: ctk.CTkToplevel) -> None:
        dialog.update_idletasks()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()

        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()

        x = parent_x + max((parent_width - width) // 2, 0)
        y = parent_y + max((parent_height - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _show_modal_dialog(
        self,
        title: str,
        message: str,
        variant: str,
        buttons: tuple[str, ...],
        cancel_value: str | None,
    ) -> str | None:
        style_map = {
            "info": ("i", "#2563eb"),
            "warning": ("!", "#d97706"),
            "error": ("x", "#dc2626"),
        }
        icon_text, icon_color = style_map.get(variant, style_map["info"])
        result: dict[str, str | None] = {"value": cancel_value}

        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.transient(self)

        content = ctk.CTkFrame(dialog)
        content.grid(row=0, column=0, padx=14, pady=14, sticky="nsew")
        content.grid_columnconfigure(1, weight=1)

        icon_label = ctk.CTkLabel(
            content,
            text=icon_text,
            text_color=icon_color,
            font=ctk.CTkFont(size=24, weight="bold"),
            width=28,
        )
        icon_label.grid(row=0, column=0, padx=(4, 12), pady=(2, 8), sticky="n")

        message_label = ctk.CTkLabel(
            content,
            text=message,
            justify="left",
            anchor="w",
            wraplength=520,
        )
        message_label.grid(row=0, column=1, padx=(0, 4), pady=(2, 8), sticky="w")

        button_frame = ctk.CTkFrame(content, fg_color="transparent")
        button_frame.grid(row=1, column=0, columnspan=2, pady=(8, 2), sticky="e")

        def close_dialog(value: str | None) -> None:
            result["value"] = value
            if dialog.winfo_exists():
                try:
                    dialog.grab_release()
                except Exception:
                    pass
                dialog.destroy()

        primary_button: ctk.CTkButton | None = None
        for index, button_text in enumerate(buttons):
            command = lambda value=button_text: close_dialog(value)
            button = ctk.CTkButton(button_frame, text=button_text, width=110, command=command)
            if index == 0:
                primary_button = button
            button.grid(row=0, column=index, padx=(8 if index > 0 else 0, 0), sticky="e")

        dialog.protocol("WM_DELETE_WINDOW", lambda: close_dialog(cancel_value))
        self._center_dialog(dialog)
        dialog.grab_set()
        dialog.focus_force()
        if primary_button is not None:
            primary_button.focus_set()
        dialog.wait_window()

        return result["value"]

    def _show_info_dialog(self, title: str, message: str) -> None:
        self._show_modal_dialog(
            title=title,
            message=message,
            variant="info",
            buttons=("OK",),
            cancel_value="OK",
        )

    def _show_warning_dialog(self, title: str, message: str) -> None:
        self._show_modal_dialog(
            title=title,
            message=message,
            variant="warning",
            buttons=("OK",),
            cancel_value="OK",
        )

    def _show_error_dialog(self, title: str, message: str) -> None:
        self._show_modal_dialog(
            title=title,
            message=message,
            variant="error",
            buttons=("OK",),
            cancel_value="OK",
        )

    def _ask_yes_no_dialog(self, title: str, message: str) -> bool:
        response = self._show_modal_dialog(
            title=title,
            message=message,
            variant="warning",
            buttons=("Ja", "Nein"),
            cancel_value="Nein",
        )
        return response == "Ja"

    def _add_directory_from_entry(self) -> None:
        raw_path = self.directory_entry.get().strip()
        if not raw_path:
            return
        if self._add_directory(raw_path, must_exist=True, save=True):
            self.directory_entry.delete(0, END)

    def _browse_directory(self) -> None:
        dialog_options: dict[str, str] = {"title": "Quell-Verzeichnis waehlen"}
        if self.browse_initial_dir and os.path.isdir(self.browse_initial_dir):
            dialog_options["initialdir"] = self.browse_initial_dir

        directory = filedialog.askdirectory(**dialog_options)
        if directory and self._add_directory(directory, must_exist=True, save=True):
            parent_dir = os.path.dirname(os.path.abspath(directory))
            self.browse_initial_dir = parent_dir if parent_dir else directory

    def _add_directory(self, raw_path: str, must_exist: bool, save: bool) -> bool:
        path = os.path.abspath(os.path.normpath(raw_path.strip().strip('"')))
        if not path:
            return False

        if must_exist and not os.path.isdir(path):
            self._show_error_dialog("Ungueltiger Pfad", f"Verzeichnis nicht gefunden:\n{path}")
            return False

        normalized = os.path.normcase(path)
        existing = {
            os.path.normcase(self.directory_listbox.get(index))
            for index in range(self.directory_listbox.size())
        }
        if normalized in existing:
            return False

        self.directory_listbox.insert(END, path)
        self._update_directory_count()
        if save:
            self._save_state()
        return True

    def _remove_selected_directory(self) -> None:
        selection = self.directory_listbox.curselection()
        if not selection:
            return
        self.directory_listbox.delete(selection[0])
        self._update_directory_count()
        self._save_state()

    def _clear_directories(self) -> None:
        if self.directory_listbox.size() == 0:
            return
        if not self._ask_yes_no_dialog(
            "Sicherheitsabfrage",
            "Sollen wirklich alle Verzeichnisse geloescht werden?",
        ):
            return
        self.directory_listbox.delete(0, END)
        self._update_directory_count()
        self._save_state()

    def _import_directories(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Verzeichnisliste importieren",
            filetypes=[
                ("JSON-Dateien", "*.json"),
                ("Textdateien", "*.txt"),
                ("Alle Dateien", "*.*"),
            ],
        )
        if not file_path:
            return

        imported_directories = self._load_directories_from_file(file_path)
        if imported_directories is None:
            return

        added = 0
        duplicates = 0
        invalid_or_missing = 0

        for raw_path in imported_directories:
            path = os.path.abspath(os.path.normpath(raw_path.strip().strip('"')))
            if not path or not os.path.isdir(path):
                invalid_or_missing += 1
                continue

            if self._add_directory(path, must_exist=False, save=False):
                added += 1
            else:
                duplicates += 1

        if added:
            self._save_state()
            self.status_var.set(f"Import abgeschlossen: {added} Verzeichnisse hinzugefuegt")

        self._show_info_dialog(
            "Import",
            (
                "Import abgeschlossen.\n"
                f"Hinzugefuegt: {added}\n"
                f"Bereits vorhanden: {duplicates}\n"
                f"Ungueltig oder nicht gefunden: {invalid_or_missing}"
            ),
        )

    def _export_directories(self) -> None:
        directories = self._get_directories()
        if not directories:
            self._show_warning_dialog("Export", "Keine Verzeichnisse zum Export vorhanden.")
            return

        suggested_name = f"videovault_verzeichnisse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = filedialog.asksaveasfilename(
            title="Verzeichnisliste exportieren",
            defaultextension=".json",
            initialfile=suggested_name,
            filetypes=[
                ("JSON-Dateien", "*.json"),
                ("Textdateien", "*.txt"),
                ("Alle Dateien", "*.*"),
            ],
        )
        if not file_path:
            return

        export_path = Path(file_path)
        file_extension = export_path.suffix.lower()
        try:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            if file_extension == ".txt":
                export_path.write_text("\n".join(directories), encoding="utf-8")
            else:
                payload = {
                    "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "directories": directories,
                }
                export_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
        except OSError as exc:
            self._show_error_dialog(
                "Export fehlgeschlagen",
                f"Datei konnte nicht gespeichert werden:\n{exc}",
            )
            return

        self._show_info_dialog(
            "Export",
            f"{len(directories)} Verzeichnisse exportiert:\n{str(export_path)}",
        )

    def _load_directories_from_file(self, file_path: str) -> list[str] | None:
        import_path = Path(file_path)
        try:
            content = import_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_error_dialog(
                "Import fehlgeschlagen",
                f"Datei konnte nicht gelesen werden:\n{exc}",
            )
            return None

        if import_path.suffix.lower() == ".json":
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                self._show_error_dialog("Import fehlgeschlagen", "JSON-Datei ist ungueltig.")
                return None

            raw_directories: object
            if isinstance(payload, list):
                raw_directories = payload
            elif isinstance(payload, dict):
                raw_directories = payload.get("directories")
            else:
                raw_directories = None

            if not isinstance(raw_directories, list):
                self._show_error_dialog(
                    "Import fehlgeschlagen",
                    "JSON muss eine Liste sein oder ein Feld 'directories' enthalten.",
                )
                return None

            return [item for item in raw_directories if isinstance(item, str)]

        return [line.strip() for line in content.splitlines() if line.strip()]

    def _update_directory_count(self) -> None:
        self.directory_count_var.set(f"Anzahl: {self.directory_listbox.size()}")

    def _normalize_appearance_mode(self, raw_mode: str) -> str:
        normalized = raw_mode.strip()
        if normalized in self.APPEARANCE_MODE_TO_LABEL:
            return normalized
        if normalized in self.APPEARANCE_LABEL_TO_MODE:
            return self.APPEARANCE_LABEL_TO_MODE[normalized]

        lowered = normalized.lower()
        if lowered == "light":
            return "Light"
        if lowered == "dark":
            return "Dark"
        return "System"

    def _set_appearance_mode(self, mode: str, save: bool) -> None:
        normalized_mode = self._normalize_appearance_mode(mode)
        self.appearance_mode = normalized_mode
        ctk.set_appearance_mode(normalized_mode)
        self.appearance_mode_var.set(self.APPEARANCE_MODE_TO_LABEL[normalized_mode])
        self._apply_theme_colors()
        if save:
            self._save_state()

    def _on_appearance_mode_changed(self, selected_label: str) -> None:
        selected_mode = self.APPEARANCE_LABEL_TO_MODE.get(selected_label, "System")
        self._set_appearance_mode(selected_mode, save=True)

    @staticmethod
    def _style_listbox(
        listbox: Listbox,
        bg_color: str,
        text_color: str,
        border_color: str,
        select_bg: str,
        select_fg: str,
    ) -> None:
        listbox.configure(
            bg=bg_color,
            fg=text_color,
            selectbackground=select_bg,
            selectforeground=select_fg,
            activestyle="none",
            highlightthickness=1,
            highlightbackground=border_color,
            highlightcolor=border_color,
            bd=0,
            relief="flat",
        )

    def _apply_theme_colors(self) -> None:
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        if is_dark:
            window_bg = "#18181b"
            list_bg = "#1f2937"
            list_fg = "#e5e7eb"
            list_border = "#374151"
            select_bg = "#2563eb"
            select_fg = "#ffffff"
            scrollbar_fg = "#1f2937"
            scrollbar_button = "#4b5563"
            scrollbar_hover = "#6b7280"
            progress_bg = "#1f2937"
            progress_fg = "#3b82f6"
        else:
            window_bg = "#f3f4f6"
            list_bg = "#ffffff"
            list_fg = "#111827"
            list_border = "#d1d5db"
            select_bg = "#2563eb"
            select_fg = "#ffffff"
            scrollbar_fg = "#f3f4f6"
            scrollbar_button = "#9ca3af"
            scrollbar_hover = "#6b7280"
            progress_bg = "#e5e7eb"
            progress_fg = "#2563eb"

        self.configure(fg_color=window_bg)
        self._style_listbox(
            self.directory_listbox,
            bg_color=list_bg,
            text_color=list_fg,
            border_color=list_border,
            select_bg=select_bg,
            select_fg=select_fg,
        )
        self._style_listbox(
            self.video_listbox,
            bg_color=list_bg,
            text_color=list_fg,
            border_color=list_border,
            select_bg=select_bg,
            select_fg=select_fg,
        )
        self.directory_scrollbar.configure(
            fg_color=scrollbar_fg,
            button_color=scrollbar_button,
            button_hover_color=scrollbar_hover,
        )
        self.video_scrollbar.configure(
            fg_color=scrollbar_fg,
            button_color=scrollbar_button,
            button_hover_color=scrollbar_hover,
        )
        self.scan_progress.configure(
            fg_color=progress_bg,
            progress_color=progress_fg,
        )
        self._set_windows_titlebar_theme(is_dark)

    def _set_windows_titlebar_theme(self, is_dark: bool) -> None:
        if sys.platform != "win32":
            return

        # Apply native dark title bar on supported Windows versions.
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1 if is_dark else 0)
            size = ctypes.sizeof(value)

            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(value),
                    size,
                )
                if result == 0:
                    break
        except Exception:
            pass

    def _set_controls_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.scan_button.configure(state=state)
        self.appearance_menu.configure(state=state)
        self.browse_button.configure(state=state)
        self.remove_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.import_button.configure(state=state)
        self.export_button.configure(state=state)
        self.duplicate_checkbox.configure(state=state)
        self.duplicate_parent_checkbox.configure(state=state)
        self.directory_entry.configure(state=state)

    def _show_scan_progress(self) -> None:
        self.scan_progress.grid()
        self.scan_progress.start()

    def _hide_scan_progress(self) -> None:
        self.scan_progress.stop()
        self.scan_progress.grid_remove()

    def start_scan(self) -> None:
        if self.is_scanning:
            return

        directories = self._get_directories()
        if not directories:
            self._show_warning_dialog(
                "Hinweis",
                "Bitte mindestens ein Quell-Verzeichnis hinterlegen.",
            )
            return

        self.is_scanning = True
        self._set_controls_state(False)
        self.status_var.set("Scan laeuft ...")
        self._show_scan_progress()

        duplicate_by_size = self.duplicate_by_size_var.get()
        duplicate_by_parent_dir = self.duplicate_by_parent_dir_var.get()
        worker = threading.Thread(
            target=self._scan_worker,
            args=(directories, duplicate_by_size, duplicate_by_parent_dir),
            daemon=True,
        )
        worker.start()

    def _scan_worker(
        self, directories: list[str], duplicate_by_size: bool, duplicate_by_parent_dir: bool
    ) -> None:
        try:
            videos, warnings = self.scanner.scan(
                directories, duplicate_by_size, duplicate_by_parent_dir
            )
        except Exception as exc:  # pragma: no cover
            self.after(0, lambda: self._scan_failed(str(exc)))
            return

        self.after(0, lambda: self._scan_finished(videos, warnings))

    def _scan_failed(self, error_message: str) -> None:
        self.is_scanning = False
        self._hide_scan_progress()
        self._set_controls_state(True)
        self.status_var.set("Scan fehlgeschlagen")
        self._show_error_dialog("Scan-Fehler", error_message)

    def _scan_finished(self, videos: list[VideoEntry], warnings: list[str]) -> None:
        self.is_scanning = False
        self._hide_scan_progress()
        self._set_controls_state(True)

        self.video_entries = videos
        self.last_scan_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._refresh_video_list()
        self._save_state()

        duplicate_groups = sum(1 for item in videos if item.is_duplicate)
        total_files = sum(len(item.paths) for item in videos)
        self.status_var.set(
            f"Scan fertig: {len(videos)} Gruppen / {total_files} Dateien / {duplicate_groups} Duplikate"
        )

        if warnings:
            preview = "\n".join(warnings[:8])
            if len(warnings) > 8:
                preview += f"\n... und {len(warnings) - 8} weitere Hinweise"
            self._show_warning_dialog("Scan-Hinweise", preview)

    def _refresh_video_list(self) -> None:
        self.video_listbox.delete(0, END)
        self.row_to_entry.clear()

        for row, item in enumerate(self.video_entries):
            label = self._format_video_label(item)
            self.video_listbox.insert(END, label)
            if item.is_duplicate:
                try:
                    self.video_listbox.itemconfig(row, fg="#dc2626")
                except Exception:
                    pass
            self.row_to_entry[row] = item

        if not self.video_entries:
            self._set_details_text("Keine Videos vorhanden. Starte einen Scan.")
        else:
            self._set_details_text("Waehle ein Video, um die gefundenen Pfade anzuzeigen.")
        self._update_statistics()

    def _format_video_label(self, item: VideoEntry) -> str:
        title = self._get_video_title(item)
        if self.duplicate_by_size_var.get() and item.sizes:
            unique_sizes = sorted(set(item.sizes))
            if len(unique_sizes) == 1:
                title = f"{title} ({self._format_size(unique_sizes[0])})"
            else:
                title = f"{title} (mehrere Groessen)"

        return title

    def _on_video_selected(self, _event: object) -> None:
        selection = self.video_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        entry = self.row_to_entry.get(index)
        if entry is None:
            return

        self._show_video_details(entry)

    def _show_video_details(self, entry: VideoEntry) -> None:
        self._clear_details_box()

        header_lines = [
            f"Titel: {self._get_video_title(entry)}",
            f"Dateiname: {entry.name}",
            f"Treffer: {len(entry.paths)}",
            f"Duplikat: {'Ja' if entry.is_duplicate else 'Nein'}",
            "",
            "Gefundene Pfade (klickbar):",
        ]
        self.details_box.insert("1.0", "\n".join(header_lines) + "\n")

        for idx, path in enumerate(entry.paths, start=1):
            size_text = ""
            if idx - 1 < len(entry.sizes):
                size_text = f" ({self._format_size(entry.sizes[idx - 1])})"

            self.details_box.insert(END, f"{idx}. ")
            start = self.details_box.index("end-1c")
            self.details_box.insert(END, path)
            end = self.details_box.index("end-1c")

            tag_name = f"path_link_{idx}"
            self.details_link_tags[tag_name] = path
            self.details_box.tag_add(tag_name, start, end)
            self.details_box.tag_config(tag_name, foreground="#2563eb", underline=1)
            self.details_box.insert(END, f"{size_text}\n")

    def _set_details_text(self, text: str) -> None:
        self._clear_details_box()
        self.details_box.insert("1.0", text)

    def _clear_details_box(self) -> None:
        self.details_box.configure(cursor="xterm")
        for tag_name in self.details_link_tags:
            self.details_box.tag_delete(tag_name)
        self.details_link_tags.clear()
        self.details_box.delete("1.0", END)

    def _on_details_click(self, event: object) -> str | None:
        if not hasattr(event, "x") or not hasattr(event, "y"):
            return None

        index = self.details_box.index(f"@{event.x},{event.y}")
        path = self._get_path_by_text_index(index)
        if path is None:
            return None

        self._open_video_path(path)
        return "break"

    def _on_details_hover(self, event: object) -> None:
        if not hasattr(event, "x") or not hasattr(event, "y"):
            return

        index = self.details_box.index(f"@{event.x},{event.y}")
        if self._get_path_by_text_index(index):
            self.details_box.configure(cursor="hand2")
        else:
            self.details_box.configure(cursor="xterm")

    def _on_details_leave(self, _event: object) -> None:
        self.details_box.configure(cursor="xterm")

    def _get_path_by_text_index(self, index: str) -> str | None:
        for tag_name in self.details_box.tag_names(index):
            selected_path = self.details_link_tags.get(tag_name)
            if selected_path:
                return selected_path
        return None

    def _open_video_path(self, path: str) -> None:
        normalized_path = os.path.abspath(path)
        if not os.path.isfile(normalized_path):
            self._show_error_dialog("Datei nicht gefunden", f"Datei nicht gefunden:\n{normalized_path}")
            return

        try:
            if os.name == "nt":
                os.startfile(normalized_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", normalized_path])
            else:
                subprocess.Popen(["xdg-open", normalized_path])
        except OSError as exc:
            self._show_error_dialog(
                "Oeffnen fehlgeschlagen",
                f"Die Datei konnte nicht geoeffnet werden:\n{normalized_path}\n\n{exc}",
            )

    def _update_statistics(self) -> None:
        found_videos = len(self.video_entries)
        duplicate_groups = sum(1 for item in self.video_entries if item.is_duplicate)
        last_scan = self.last_scan_at if self.last_scan_at else "Nie"

        self.stats_videos_var.set(str(found_videos))
        self.stats_last_scan_var.set(last_scan)
        self.stats_duplicates_var.set(str(duplicate_groups))

    @staticmethod
    def _get_video_title(entry: VideoEntry) -> str:
        parent_names: list[str] = []
        for path in entry.paths:
            parent_name = Path(path).parent.name.strip()
            if parent_name:
                parent_names.append(parent_name)

        if not parent_names:
            return entry.name

        unique_parents = sorted(set(parent_names), key=str.lower)
        if len(unique_parents) == 1:
            return unique_parents[0]

        return f"{unique_parents[0]} (+{len(unique_parents) - 1} weitere Ordner)"

    def _save_state(self) -> None:
        self.store.save(
            directories=self._get_directories(),
            duplicate_by_size=self.duplicate_by_size_var.get(),
            duplicate_by_parent_dir=self.duplicate_by_parent_dir_var.get(),
            last_scan_at=self.last_scan_at,
            videos=self.video_entries,
            appearance_mode=self.appearance_mode,
        )

    def _on_duplicate_mode_changed(self) -> None:
        self._refresh_video_list()
        self._save_state()

    @staticmethod
    def _format_size(size_in_bytes: int) -> str:
        value = float(size_in_bytes)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{size_in_bytes} B"


def main() -> None:
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = VideoVaultApp()
    app.mainloop()


if __name__ == "__main__":
    # EXE build (PyInstaller):
    # pyinstaller --onefile --windowed --name VideoVault main.py
    main()
