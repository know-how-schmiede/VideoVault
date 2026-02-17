from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import END, Listbox, SINGLE, filedialog
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import customtkinter as ctk

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

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

    def load(self) -> tuple[list[str], bool, bool, str | None, list[VideoEntry], str, str]:
        if not self.file_path.exists():
            return [], False, False, None, [], "System", ""

        try:
            with self.file_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return [], False, False, None, [], "System", ""

        raw_dirs = payload.get("directories", [])
        duplicate_by_size = bool(payload.get("duplicate_by_size", False))
        duplicate_by_parent_dir = bool(payload.get("duplicate_by_parent_dir", False))
        raw_last_scan_at = payload.get("last_scan_at")
        raw_videos = payload.get("videos", [])
        raw_appearance_mode = payload.get("appearance_mode", "System")
        raw_tmdb_api_key = payload.get("tmdb_api_key", "")
        last_scan_at = raw_last_scan_at if isinstance(raw_last_scan_at, str) else None
        appearance_mode = raw_appearance_mode if isinstance(raw_appearance_mode, str) else "System"
        tmdb_api_key = raw_tmdb_api_key if isinstance(raw_tmdb_api_key, str) else ""

        directories = [item for item in raw_dirs if isinstance(item, str)]
        videos: list[VideoEntry] = []
        if isinstance(raw_videos, list):
            for item in raw_videos:
                if isinstance(item, dict):
                    entry = VideoEntry.from_dict(item)
                    if entry is not None:
                        videos.append(entry)

        return (
            directories,
            duplicate_by_size,
            duplicate_by_parent_dir,
            last_scan_at,
            videos,
            appearance_mode,
            tmdb_api_key,
        )

    def save(
        self,
        directories: list[str],
        duplicate_by_size: bool,
        duplicate_by_parent_dir: bool,
        last_scan_at: str | None,
        videos: list[VideoEntry],
        appearance_mode: str,
        tmdb_api_key: str,
    ) -> None:
        payload = {
            "directories": directories,
            "duplicate_by_size": duplicate_by_size,
            "duplicate_by_parent_dir": duplicate_by_parent_dir,
            "last_scan_at": last_scan_at,
            "videos": [video.to_dict() for video in videos],
            "appearance_mode": appearance_mode,
            "tmdb_api_key": tmdb_api_key,
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
                warnings.append(f"Directory not found: {directory}")
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
                        warnings.append(f"File not readable: {full_path}")
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
            name = group["name"] if isinstance(group["name"], str) else "Unknown"
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
    COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
    TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w780"
    TMDB_LANGUAGES = ("de-DE", "en-US")
    APPEARANCE_LABEL_TO_MODE = {
        "System": "System",
        "Light": "Light",
        "Dark": "Dark",
    }
    APPEARANCE_MODE_TO_LABEL = {
        "System": "System",
        "Light": "Light",
        "Dark": "Dark",
    }

    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("1200x760")
        self.minsize(980, 620)

        self.store = JsonStore(self._get_data_root() / self.DATA_FILE)
        self.scanner = VideoScanner()

        self.video_entries: list[VideoEntry] = []
        self.row_to_entry: dict[int, VideoEntry] = {}
        self.is_scanning = False
        self.is_downloading_metadata = False
        self.last_scan_at: str | None = None
        self.details_link_targets: dict[str, tuple[str, str]] = {}
        self.cover_image: ctk.CTkImage | None = None
        self.cover_placeholder_image: ctk.CTkImage | None = None

        self.duplicate_by_size_var = ctk.BooleanVar(value=False)
        self.duplicate_by_parent_dir_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="Ready")
        self.stats_videos_var = ctk.StringVar(value="0")
        self.stats_last_scan_var = ctk.StringVar(value="Never")
        self.stats_duplicates_var = ctk.StringVar(value="0")
        self.directory_count_var = ctk.StringVar(value="Count: 0")
        self.appearance_mode = "System"
        self.appearance_mode_var = ctk.StringVar(value="System")
        self.tmdb_api_key = ""
        self.browse_initial_dir: str | None = None

        self._build_layout()
        self._load_saved_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _get_data_root() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent

        script_dir = Path(__file__).resolve().parent
        if script_dir.name.lower() == "src":
            return script_dir.parent
        return script_dir

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
            text="Duplicate check by file size",
            variable=self.duplicate_by_size_var,
            onvalue=True,
            offvalue=False,
            command=self._on_duplicate_mode_changed,
        )
        self.duplicate_checkbox.grid(row=0, column=1, padx=8, pady=12, sticky="e")

        self.duplicate_parent_checkbox = ctk.CTkCheckBox(
            top_bar,
            text="Duplicate key: parent directory",
            variable=self.duplicate_by_parent_dir_var,
            onvalue=True,
            offvalue=False,
            command=self._on_duplicate_mode_changed,
        )
        self.duplicate_parent_checkbox.grid(row=0, column=2, padx=8, pady=12, sticky="e")

        ctk.CTkLabel(top_bar, text="Theme").grid(row=0, column=3, padx=(8, 4), pady=12, sticky="e")
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

        ctk.CTkLabel(header, text="Source directories").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, textvariable=self.directory_count_var).grid(row=0, column=1, sticky="e")

        self.directory_entry = ctk.CTkEntry(panel, placeholder_text="Enter path and press Enter")
        self.directory_entry.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        self.directory_entry.bind("<Return>", lambda _event: self._add_directory_from_entry())

        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        controls.grid_columnconfigure(0, weight=1)

        self.browse_button = ctk.CTkButton(
            controls, text="Choose folder", command=self._browse_directory
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
            footer, text="Remove", command=self._remove_selected_directory
        )
        self.remove_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.clear_button = ctk.CTkButton(
            footer, text="Clear all", command=self._clear_directories
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

        ctk.CTkLabel(panel, text="Found videos").grid(
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
        panel.grid_rowconfigure(1, weight=2)
        panel.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(panel, text="Details").grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")

        self.details_box = ctk.CTkTextbox(panel, wrap="word")
        self.details_box.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="nsew")
        self.details_box.bind("<Button-1>", self._on_details_click, add="+")
        self.details_box.bind("<Motion>", self._on_details_hover, add="+")
        self.details_box.bind("<Leave>", self._on_details_leave, add="+")
        self.details_box.bind("<Key>", lambda _event: "break")
        self._set_details_text("Select a video to show the found paths.")

        ctk.CTkLabel(panel, text="Statistics").grid(row=2, column=0, padx=12, pady=(0, 6), sticky="w")

        stats_frame = ctk.CTkFrame(panel)
        stats_frame.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        stats_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(stats_frame, text="Found videos:").grid(
            row=0, column=0, padx=10, pady=(10, 4), sticky="w"
        )
        ctk.CTkLabel(stats_frame, textvariable=self.stats_videos_var).grid(
            row=0, column=1, padx=10, pady=(10, 4), sticky="e"
        )
        ctk.CTkLabel(stats_frame, text="Last scan:").grid(
            row=1, column=0, padx=10, pady=4, sticky="w"
        )
        ctk.CTkLabel(stats_frame, textvariable=self.stats_last_scan_var).grid(
            row=1, column=1, padx=10, pady=4, sticky="e"
        )
        ctk.CTkLabel(stats_frame, text="Duplicate groups:").grid(
            row=2, column=0, padx=10, pady=(4, 10), sticky="w"
        )
        ctk.CTkLabel(stats_frame, textvariable=self.stats_duplicates_var).grid(
            row=2, column=1, padx=10, pady=(4, 10), sticky="e"
        )

        ctk.CTkLabel(panel, text="Movie metadata").grid(row=4, column=0, padx=12, pady=(0, 6), sticky="w")

        metadata_frame = ctk.CTkFrame(panel)
        metadata_frame.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="nsew")
        metadata_frame.grid_columnconfigure(0, weight=0)
        metadata_frame.grid_columnconfigure(1, weight=1)
        metadata_frame.grid_rowconfigure(1, weight=1)

        self.cover_label = ctk.CTkLabel(
            metadata_frame,
            text="No cover found",
            width=220,
            height=320,
            anchor="center",
            justify="center",
            compound="center",
            fg_color=("gray90", "gray20"),
            corner_radius=8,
        )
        self.cover_label.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10, sticky="n")
        if Image is not None:
            placeholder = Image.new("RGB", (2, 2), color=(0, 0, 0))
            self.cover_placeholder_image = ctk.CTkImage(
                light_image=placeholder,
                dark_image=placeholder,
                size=(2, 2),
            )

        metadata_header = ctk.CTkFrame(metadata_frame, fg_color="transparent")
        metadata_header.grid(row=0, column=1, padx=(0, 10), pady=(10, 6), sticky="ew")
        metadata_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(metadata_header, text="Description").grid(row=0, column=0, sticky="w")
        self.download_metadata_button = ctk.CTkButton(
            metadata_header,
            text="Download from internet",
            width=180,
            command=self._download_selected_metadata,
        )
        self.download_metadata_button.grid(row=0, column=1, padx=(0, 6), sticky="e")
        self.tmdb_key_button = ctk.CTkButton(
            metadata_header,
            text="Set TMDB key",
            width=130,
            command=self._open_tmdb_key_dialog,
        )
        self.tmdb_key_button.grid(row=0, column=2, sticky="e")

        self.description_box = ctk.CTkTextbox(metadata_frame, wrap="word")
        self.description_box.grid(row=1, column=1, padx=(0, 10), pady=(0, 10), sticky="nsew")
        self.description_box.bind("<Key>", lambda _event: "break")
        self._reset_movie_metadata()

    def _load_saved_state(self) -> None:
        (
            directories,
            duplicate_by_size,
            duplicate_by_parent_dir,
            last_scan_at,
            videos,
            appearance_mode,
            tmdb_api_key,
        ) = self.store.load()
        self.duplicate_by_size_var.set(duplicate_by_size)
        self.duplicate_by_parent_dir_var.set(duplicate_by_parent_dir)
        self.last_scan_at = last_scan_at
        self.tmdb_api_key = tmdb_api_key.strip()
        self._set_appearance_mode(appearance_mode, save=False)

        for directory in directories:
            self._add_directory(directory, must_exist=False, save=False)

        self.video_entries = videos
        self._refresh_video_list()
        if videos:
            total_files = sum(len(item.paths) for item in videos)
            self.status_var.set(f"{len(videos)} groups / {total_files} files loaded")

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
            buttons=("Yes", "No"),
            cancel_value="No",
        )
        return response == "Yes"

    def _add_directory_from_entry(self) -> None:
        raw_path = self.directory_entry.get().strip()
        if not raw_path:
            return
        if self._add_directory(raw_path, must_exist=True, save=True):
            self.directory_entry.delete(0, END)

    def _browse_directory(self) -> None:
        dialog_options: dict[str, str] = {"title": "Choose source directory"}
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
            self._show_error_dialog("Invalid path", f"Directory not found:\n{path}")
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
            "Confirm action",
            "Do you really want to remove all directories?",
        ):
            return
        self.directory_listbox.delete(0, END)
        self._update_directory_count()
        self._save_state()

    def _import_directories(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Import directory list",
            filetypes=[
                ("JSON files", "*.json"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
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
            self.status_var.set(f"Import completed: {added} directories added")

        self._show_info_dialog(
            "Import",
            (
                "Import completed.\n"
                f"Added: {added}\n"
                f"Already present: {duplicates}\n"
                f"Invalid or missing: {invalid_or_missing}"
            ),
        )

    def _export_directories(self) -> None:
        directories = self._get_directories()
        if not directories:
            self._show_warning_dialog("Export", "No directories available for export.")
            return

        suggested_name = f"videovault_directories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = filedialog.asksaveasfilename(
            title="Export directory list",
            defaultextension=".json",
            initialfile=suggested_name,
            filetypes=[
                ("JSON files", "*.json"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
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
                "Export failed",
                f"File could not be saved:\n{exc}",
            )
            return

        self._show_info_dialog(
            "Export",
            f"{len(directories)} directories exported:\n{str(export_path)}",
        )

    def _load_directories_from_file(self, file_path: str) -> list[str] | None:
        import_path = Path(file_path)
        try:
            content = import_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            self._show_error_dialog(
                "Import failed",
                f"File could not be read:\n{exc}",
            )
            return None

        if import_path.suffix.lower() == ".json":
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                self._show_error_dialog("Import failed", "JSON file is invalid.")
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
                    "Import failed",
                    "JSON must be a list or contain a 'directories' field.",
                )
                return None

            return [item for item in raw_directories if isinstance(item, str)]

        return [line.strip() for line in content.splitlines() if line.strip()]

    def _update_directory_count(self) -> None:
        self.directory_count_var.set(f"Count: {self.directory_listbox.size()}")

    def _normalize_appearance_mode(self, raw_mode: str) -> str:
        normalized = raw_mode.strip()
        if normalized in self.APPEARANCE_MODE_TO_LABEL:
            return normalized
        if normalized in self.APPEARANCE_LABEL_TO_MODE:
            return self.APPEARANCE_LABEL_TO_MODE[normalized]

        lowered = normalized.lower()
        if lowered in ("light", "hell"):
            return "Light"
        if lowered in ("dark", "dunkel"):
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
        if hasattr(self, "download_metadata_button"):
            self.download_metadata_button.configure(state=state)
        if hasattr(self, "tmdb_key_button"):
            self.tmdb_key_button.configure(state=state)

    def _show_scan_progress(self) -> None:
        self.scan_progress.grid()
        self.scan_progress.start()

    def _hide_scan_progress(self) -> None:
        self.scan_progress.stop()
        self.scan_progress.grid_remove()

    def start_scan(self) -> None:
        if self.is_scanning:
            return
        if self.is_downloading_metadata:
            self._show_warning_dialog(
                "Notice",
                "Please wait until metadata download has finished.",
            )
            return

        directories = self._get_directories()
        if not directories:
            self._show_warning_dialog(
                "Notice",
                "Please add at least one source directory.",
            )
            return

        self.is_scanning = True
        self._set_controls_state(False)
        self.status_var.set("Scan running ...")
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
            error_message = str(exc)
            self.after(0, lambda msg=error_message: self._scan_failed(msg))
            return

        self.after(0, lambda: self._scan_finished(videos, warnings))

    def _scan_failed(self, error_message: str) -> None:
        self.is_scanning = False
        self._hide_scan_progress()
        self._set_controls_state(True)
        self.status_var.set("Scan failed")
        self._show_error_dialog("Scan error", error_message)

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
            f"Scan finished: {len(videos)} groups / {total_files} files / {duplicate_groups} duplicates"
        )

        if warnings:
            preview = "\n".join(warnings[:8])
            if len(warnings) > 8:
                preview += f"\n... and {len(warnings) - 8} more warnings"
            self._show_warning_dialog("Scan warnings", preview)

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
            self._set_details_text("No videos available. Start a scan.")
            self._reset_movie_metadata("No description available.")
        else:
            self._set_details_text("Select a video to show the found paths.")
            self._reset_movie_metadata()
        self._update_statistics()

    def _format_video_label(self, item: VideoEntry) -> str:
        title = self._get_video_title(item)
        if self.duplicate_by_size_var.get() and item.sizes:
            unique_sizes = sorted(set(item.sizes))
            if len(unique_sizes) == 1:
                title = f"{title} ({self._format_size(unique_sizes[0])})"
            else:
                title = f"{title} (multiple sizes)"

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
            f"Title: {self._get_video_title(entry)}",
            f"Filename: {entry.name}",
            f"Matches: {len(entry.paths)}",
            f"Duplicate: {'Yes' if entry.is_duplicate else 'No'}",
            "",
            "Found paths (clickable):",
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
            self.details_link_targets[tag_name] = ("video", path)
            self.details_box.tag_add(tag_name, start, end)
            self.details_box.tag_config(tag_name, foreground="#2563eb", underline=1)
            if size_text:
                self.details_box.insert(END, size_text)
            self.details_box.insert(END, "  ")

            folder_link_label = "[Open folder]"
            folder_start = self.details_box.index("end-1c")
            self.details_box.insert(END, folder_link_label)
            folder_end = self.details_box.index("end-1c")

            folder_tag = f"folder_link_{idx}"
            self.details_link_targets[folder_tag] = ("folder", path)
            self.details_box.tag_add(folder_tag, folder_start, folder_end)
            self.details_box.tag_config(folder_tag, foreground="#059669", underline=1)
            self.details_box.insert(END, "\n")

        self._update_movie_metadata(entry)

    def _reset_movie_metadata(
        self,
        description_text: str = "Select a video to load description and cover.",
    ) -> None:
        self._set_description_text(description_text)
        self._set_cover_image(None)

    def _update_movie_metadata(self, entry: VideoEntry) -> None:
        if not entry.paths:
            self._reset_movie_metadata("No description available.")
            return

        primary_video_path = Path(entry.paths[0])
        description_path = self._find_description_file(primary_video_path)
        description_text = (
            self._load_description_text(description_path) if description_path is not None else None
        )
        if description_text:
            self._set_description_text(description_text)
        else:
            self._set_description_text(
                "No local description found.\nUse 'Download from internet' to fetch metadata.\n\nSupported files:\n"
                "- <video>.nfo / movie.nfo / info.nfo\n"
                "- <video>.txt / description.txt / plot.txt / details.txt"
            )

        cover_path = self._find_cover_file(primary_video_path)
        self._set_cover_image(cover_path)

    def _download_selected_metadata(self) -> None:
        if self.is_scanning or self.is_downloading_metadata:
            return

        if not self._get_active_tmdb_api_key():
            if self._ask_yes_no_dialog(
                "TMDB key required",
                "No TMDB API key is configured.\n\n"
                "Open the key form now?",
            ):
                self._open_tmdb_key_dialog()
            return

        selected_entry = self._get_selected_video_entry()
        if selected_entry is None:
            self._show_warning_dialog("Notice", "Select a video first.")
            return
        if not selected_entry.paths:
            self._show_warning_dialog("Notice", "No valid path found for this entry.")
            return

        description_path, cover_path = self._get_metadata_sidecar_paths(selected_entry)
        existing_targets = [
            str(path)
            for path in (description_path, cover_path)
            if path.is_file()
        ]
        if existing_targets:
            overwrite_message = (
                "Metadata files already exist and will be overwritten:\n\n"
                f"{chr(10).join(existing_targets)}\n\nContinue?"
            )
            if not self._ask_yes_no_dialog("Overwrite metadata", overwrite_message):
                return

        self.is_downloading_metadata = True
        self.download_metadata_button.configure(state="disabled")
        self.status_var.set("Downloading metadata ...")
        worker = threading.Thread(
            target=self._download_metadata_worker,
            args=(selected_entry, description_path, cover_path),
            daemon=True,
        )
        worker.start()

    def _download_metadata_worker(
        self,
        entry: VideoEntry,
        description_path: Path,
        cover_path: Path,
    ) -> None:
        try:
            metadata = self._fetch_metadata_from_tmdb(entry)
            self._write_nfo_file(description_path, metadata)
            cover_saved = self._download_cover_image(metadata, cover_path)
        except Exception as exc:  # pragma: no cover
            error_message = str(exc)
            self.after(0, lambda msg=error_message: self._metadata_download_failed(msg))
            return

        self.after(
            0,
            lambda: self._metadata_download_finished(
                entry=entry,
                description_path=description_path,
                cover_path=cover_path,
                cover_saved=cover_saved,
            ),
        )

    def _metadata_download_finished(
        self,
        entry: VideoEntry,
        description_path: Path,
        cover_path: Path,
        cover_saved: bool,
    ) -> None:
        self.is_downloading_metadata = False
        if not self.is_scanning:
            self.download_metadata_button.configure(state="normal")

        cover_message = f" + {cover_path.name}" if cover_saved else ""
        self.status_var.set(f"Metadata saved: {description_path.name}{cover_message}")

        selected_entry = self._get_selected_video_entry()
        if (
            selected_entry is not None
            and selected_entry.paths
            and entry.paths
            and selected_entry.paths[0] == entry.paths[0]
        ):
            self._show_video_details(selected_entry)

    def _metadata_download_failed(self, error_message: str) -> None:
        self.is_downloading_metadata = False
        if not self.is_scanning:
            self.download_metadata_button.configure(state="normal")
        self.status_var.set("Metadata download failed")
        self._show_error_dialog("Metadata download failed", error_message)

    def _fetch_metadata_from_tmdb(self, entry: VideoEntry) -> dict[str, str]:
        api_key = self._get_active_tmdb_api_key()
        if not api_key:
            raise RuntimeError(
                "TMDB API key is not configured.\n\n"
                "Use 'Set TMDB key' in the app or set an environment variable:\n"
                "PowerShell: $env:TMDB_API_KEY = '<your_key>'"
            )

        search_title, release_year = self._build_movie_search_query(entry)
        if not search_title:
            raise RuntimeError("Could not build a search title for this movie.")

        search_params = {
            "api_key": api_key,
            "query": search_title,
            "include_adult": "false",
        }
        if release_year:
            search_params["year"] = release_year

        search_payload = self._tmdb_request_json("/search/movie", search_params)
        raw_results = search_payload.get("results", [])
        if not isinstance(raw_results, list) or not raw_results:
            raise RuntimeError(f"No TMDB match found for '{search_title}'.")

        movie_candidate = self._select_tmdb_result(raw_results, release_year)
        movie_id = movie_candidate.get("id")
        if not isinstance(movie_id, int):
            raise RuntimeError("TMDB response does not contain a valid movie id.")

        details = self._tmdb_request_json(
            f"/movie/{movie_id}",
            {
                "api_key": api_key,
                "language": self.TMDB_LANGUAGES[0],
            },
        )
        if not isinstance(details, dict):
            raise RuntimeError("TMDB details response is invalid.")

        overview = str(details.get("overview", "")).strip()
        if not overview and len(self.TMDB_LANGUAGES) > 1:
            fallback_details = self._tmdb_request_json(
                f"/movie/{movie_id}",
                {
                    "api_key": api_key,
                    "language": self.TMDB_LANGUAGES[1],
                },
            )
            if isinstance(fallback_details, dict):
                overview = str(fallback_details.get("overview", "")).strip() or overview
                if not details.get("poster_path") and fallback_details.get("poster_path"):
                    details["poster_path"] = fallback_details.get("poster_path")

        release_date = str(details.get("release_date", "")).strip()
        year_text = release_date[:4] if len(release_date) >= 4 else (release_year or "")
        poster_path = str(details.get("poster_path", "")).strip()
        poster_url = (
            f"{self.TMDB_IMAGE_BASE_URL}{poster_path}"
            if poster_path.startswith("/")
            else ""
        )
        rating_value = details.get("vote_average")
        rating_text = ""
        if isinstance(rating_value, (int, float)):
            rating_text = f"{float(rating_value):.1f}"

        return {
            "title": str(details.get("title", "")).strip() or search_title,
            "original_title": str(details.get("original_title", "")).strip(),
            "overview": overview,
            "year": year_text,
            "rating": rating_text,
            "tmdb_id": str(movie_id),
            "release_date": release_date,
            "poster_url": poster_url,
        }

    def _tmdb_request_json(self, endpoint: str, params: dict[str, str]) -> dict[str, object]:
        query = urlencode(params)
        url = f"{self.TMDB_API_BASE_URL}{endpoint}?{query}"
        request = Request(url, headers={"User-Agent": "VideoVault/0.5.2"})
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
        except HTTPError as exc:
            raise RuntimeError(f"TMDB request failed ({exc.code}).") from exc
        except URLError as exc:
            raise RuntimeError(f"TMDB connection failed: {exc.reason}") from exc

        try:
            parsed_payload = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("TMDB response could not be parsed.") from exc

        if not isinstance(parsed_payload, dict):
            raise RuntimeError("TMDB response has an unexpected format.")
        return parsed_payload

    @staticmethod
    def _select_tmdb_result(
        results: list[object],
        release_year: str | None,
    ) -> dict[str, object]:
        valid_results = [item for item in results if isinstance(item, dict)]
        if not valid_results:
            raise RuntimeError("TMDB did not return valid movie results.")

        if release_year:
            year_matched = [
                item
                for item in valid_results
                if str(item.get("release_date", "")).startswith(release_year)
            ]
            if year_matched:
                return year_matched[0]

        return valid_results[0]

    @staticmethod
    def _build_movie_search_query(entry: VideoEntry) -> tuple[str, str | None]:
        candidates: list[str] = []
        if entry.paths:
            candidates.append(Path(entry.paths[0]).parent.name)
        candidates.append(Path(entry.name).stem)

        for candidate in candidates:
            compact = candidate.strip()
            if not compact:
                continue

            year_match = re.search(r"(19|20)\d{2}", compact)
            year = year_match.group(0) if year_match else None

            cleaned = re.sub(r"[\[\(](19|20)\d{2}[\]\)]", " ", compact)
            cleaned = re.sub(r"\b(19|20)\d{2}\b", " ", cleaned)
            cleaned = re.sub(r"[._]+", " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.")
            if cleaned:
                return cleaned, year

        return "", None

    @staticmethod
    def _get_metadata_sidecar_paths(entry: VideoEntry) -> tuple[Path, Path]:
        if not entry.paths:
            raise RuntimeError("Entry does not contain any file path.")

        movie_dir = Path(entry.paths[0]).resolve().parent
        return movie_dir / "movie.nfo", movie_dir / "poster.jpg"

    @staticmethod
    def _write_nfo_file(path: Path, metadata: dict[str, str]) -> None:
        movie = ET.Element("movie")

        def add_node(tag: str, key: str) -> None:
            value = metadata.get(key, "").strip()
            if value:
                ET.SubElement(movie, tag).text = value

        add_node("title", "title")
        add_node("originaltitle", "original_title")
        add_node("year", "year")
        add_node("plot", "overview")
        add_node("outline", "overview")
        add_node("rating", "rating")
        add_node("premiered", "release_date")
        add_node("tmdbid", "tmdb_id")

        path.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(movie)
        tree.write(path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _download_cover_image(metadata: dict[str, str], target_path: Path) -> bool:
        poster_url = metadata.get("poster_url", "").strip()
        if not poster_url:
            return False

        request = Request(poster_url, headers={"User-Agent": "VideoVault/0.5.2"})
        try:
            with urlopen(request, timeout=20) as response:
                image_data = response.read()
        except (HTTPError, URLError, OSError):
            return False

        if not image_data:
            return False

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(image_data)
        except OSError:
            return False
        return True

    def _get_active_tmdb_api_key(self) -> str:
        configured_key = self.tmdb_api_key.strip()
        if configured_key:
            return configured_key

        return os.environ.get("TMDB_API_KEY", "").strip()

    def _open_tmdb_key_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("TMDB API key")
        dialog.resizable(False, False)
        dialog.transient(self)

        content = ctk.CTkFrame(dialog)
        content.grid(row=0, column=0, padx=14, pady=14, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            content,
            text="Enter your TMDB API key.",
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        key_entry = ctk.CTkEntry(content, width=420, show="*")
        key_entry.grid(row=1, column=0, pady=(8, 6), sticky="ew")
        if self.tmdb_api_key:
            key_entry.insert(0, self.tmdb_api_key)
        elif os.environ.get("TMDB_API_KEY", "").strip():
            key_entry.insert(0, os.environ["TMDB_API_KEY"].strip())

        show_key_var = ctk.BooleanVar(value=False)

        def toggle_show_key() -> None:
            key_entry.configure(show="" if show_key_var.get() else "*")

        ctk.CTkCheckBox(
            content,
            text="Show key",
            variable=show_key_var,
            onvalue=True,
            offvalue=False,
            command=toggle_show_key,
        ).grid(row=2, column=0, pady=(0, 6), sticky="w")

        ctk.CTkLabel(
            content,
            text=(
                "The key is stored in the local file 'videovault_data.json'.\n"
                "If no key is stored, the app will use TMDB_API_KEY from the environment."
            ),
            justify="left",
            anchor="w",
            wraplength=460,
        ).grid(row=3, column=0, pady=(0, 8), sticky="w")

        button_row = ctk.CTkFrame(content, fg_color="transparent")
        button_row.grid(row=4, column=0, sticky="e")

        def close_dialog() -> None:
            if dialog.winfo_exists():
                try:
                    dialog.grab_release()
                except Exception:
                    pass
                dialog.destroy()

        def save_key() -> None:
            entered_key = key_entry.get().strip()
            if not entered_key:
                self._show_warning_dialog(
                    "TMDB API key",
                    "Enter a key or use 'Clear saved key'.",
                )
                return

            self.tmdb_api_key = entered_key
            self._save_state()
            self.status_var.set("TMDB key saved")
            close_dialog()

        def clear_key() -> None:
            self.tmdb_api_key = ""
            self._save_state()
            self.status_var.set("Saved TMDB key cleared")
            close_dialog()

        ctk.CTkButton(
            button_row,
            text="Clear saved key",
            width=140,
            command=clear_key,
        ).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(
            button_row,
            text="Cancel",
            width=100,
            command=close_dialog,
        ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            button_row,
            text="Save",
            width=100,
            command=save_key,
        ).grid(row=0, column=2)

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        self._center_dialog(dialog)
        dialog.grab_set()
        dialog.focus_force()
        key_entry.focus_set()
        dialog.wait_window()

    def _get_selected_video_entry(self) -> VideoEntry | None:
        selection = self.video_listbox.curselection()
        if not selection:
            return None

        selected_index = selection[0]
        return self.row_to_entry.get(selected_index)

    def _find_description_file(self, video_path: Path) -> Path | None:
        directory = video_path.parent
        stem = video_path.stem
        candidates = [
            directory / f"{stem}.nfo",
            directory / f"{stem}.txt",
            directory / "movie.nfo",
            directory / "info.nfo",
            directory / "description.txt",
            directory / "plot.txt",
            directory / "details.txt",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _find_cover_file(self, video_path: Path) -> Path | None:
        directory = video_path.parent
        stem = video_path.stem
        for extension in self.COVER_EXTENSIONS:
            candidates = (
                directory / f"{stem}-poster{extension}",
                directory / f"{stem}{extension}",
                directory / f"{directory.name}{extension}",
                directory / f"poster{extension}",
                directory / f"folder{extension}",
                directory / f"cover{extension}",
                directory / f"movie{extension}",
            )
            for candidate in candidates:
                if candidate.is_file():
                    return candidate
        return None

    def _load_description_text(self, file_path: Path) -> str | None:
        raw_text = self._read_text_file(file_path)
        if raw_text is None:
            return None

        text = raw_text.strip()
        if not text:
            return None

        if file_path.suffix.lower() == ".nfo":
            extracted_text = self._extract_description_from_nfo(text)
            if extracted_text:
                text = extracted_text

        if len(text) > 3500:
            text = f"{text[:3500].rstrip()}..."
        return text

    @staticmethod
    def _read_text_file(file_path: Path) -> str | None:
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError:
                return None
        return None

    @staticmethod
    def _extract_description_from_nfo(nfo_text: str) -> str | None:
        try:
            root = ET.fromstring(nfo_text)
        except ET.ParseError:
            return None

        for tag_name in ("plot", "outline", "description", "overview", "summary"):
            node = root.find(f".//{tag_name}")
            if node is None:
                continue

            node_text = " ".join("".join(node.itertext()).split())
            if node_text:
                return node_text
        return None

    def _set_cover_image(self, cover_path: Path | None) -> None:
        new_image: ctk.CTkImage | None = None
        fallback_text = "No cover found"

        if cover_path is None:
            fallback_text = "No cover found"
        elif Image is None:
            fallback_text = (
                f"Cover found:\n{cover_path.name}\n\n"
                "Install Pillow to display it."
            )
        else:
            try:
                with Image.open(cover_path) as source:
                    prepared = source.convert("RGB")

                resampling_class = getattr(Image, "Resampling", Image)
                resampling = getattr(
                    resampling_class,
                    "LANCZOS",
                    getattr(Image, "LANCZOS", 1),
                )
                prepared.thumbnail((220, 320), resampling)
                new_image = ctk.CTkImage(
                    light_image=prepared,
                    dark_image=prepared,
                    size=prepared.size,
                )
            except Exception:
                fallback_text = f"Could not load cover:\n{cover_path.name}"

        if new_image is None:
            if self.cover_placeholder_image is not None:
                self.cover_image = self.cover_placeholder_image
                self.cover_label.configure(image=self.cover_image, text=fallback_text)
            else:
                self.cover_label.configure(text=fallback_text)
                self.cover_image = None
            return

        self.cover_image = new_image
        self.cover_label.configure(image=self.cover_image, text="")

    def _set_description_text(self, text: str) -> None:
        self.description_box.configure(state="normal")
        self.description_box.delete("1.0", END)
        self.description_box.insert("1.0", text)
        self.description_box.configure(state="disabled")

    def _set_details_text(self, text: str) -> None:
        self._clear_details_box()
        self.details_box.insert("1.0", text)

    def _clear_details_box(self) -> None:
        self.details_box.configure(cursor="xterm")
        for tag_name in self.details_link_targets:
            self.details_box.tag_delete(tag_name)
        self.details_link_targets.clear()
        self.details_box.delete("1.0", END)

    def _on_details_click(self, event: object) -> str | None:
        if not hasattr(event, "x") or not hasattr(event, "y"):
            return None

        index = self.details_box.index(f"@{event.x},{event.y}")
        action = self._get_details_action_by_text_index(index)
        if action is None:
            return None

        action_name, target_path = action
        if action_name == "folder":
            self._open_parent_folder(target_path)
        else:
            self._open_video_path(target_path)
        return "break"

    def _on_details_hover(self, event: object) -> None:
        if not hasattr(event, "x") or not hasattr(event, "y"):
            return

        index = self.details_box.index(f"@{event.x},{event.y}")
        if self._get_details_action_by_text_index(index):
            self.details_box.configure(cursor="hand2")
        else:
            self.details_box.configure(cursor="xterm")

    def _on_details_leave(self, _event: object) -> None:
        self.details_box.configure(cursor="xterm")

    def _get_details_action_by_text_index(self, index: str) -> tuple[str, str] | None:
        for tag_name in self.details_box.tag_names(index):
            selected_target = self.details_link_targets.get(tag_name)
            if selected_target:
                return selected_target
        return None

    def _open_video_path(self, path: str) -> None:
        normalized_path = os.path.abspath(path)
        if not os.path.isfile(normalized_path):
            self._show_error_dialog("File not found", f"File not found:\n{normalized_path}")
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
                "Open failed",
                f"The file could not be opened:\n{normalized_path}\n\n{exc}",
            )

    def _open_parent_folder(self, path: str) -> None:
        normalized_path = os.path.abspath(path)
        parent_folder = str(Path(normalized_path).parent)
        if not os.path.isdir(parent_folder):
            self._show_error_dialog("Folder not found", f"Parent folder not found:\n{parent_folder}")
            return

        try:
            if os.name == "nt":
                os.startfile(parent_folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", parent_folder])
            else:
                subprocess.Popen(["xdg-open", parent_folder])
        except OSError as exc:
            self._show_error_dialog(
                "Open folder failed",
                f"The folder could not be opened:\n{parent_folder}\n\n{exc}",
            )

    def _update_statistics(self) -> None:
        found_videos = len(self.video_entries)
        duplicate_groups = sum(1 for item in self.video_entries if item.is_duplicate)
        last_scan = self.last_scan_at if self.last_scan_at else "Never"

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

        return f"{unique_parents[0]} (+{len(unique_parents) - 1} more folders)"

    def _save_state(self) -> None:
        self.store.save(
            directories=self._get_directories(),
            duplicate_by_size=self.duplicate_by_size_var.get(),
            duplicate_by_parent_dir=self.duplicate_by_parent_dir_var.get(),
            last_scan_at=self.last_scan_at,
            videos=self.video_entries,
            appearance_mode=self.appearance_mode,
            tmdb_api_key=self.tmdb_api_key,
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
    # pyinstaller --onefile --windowed --name VideoVault src/main.py
    main()
