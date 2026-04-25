"""GameDownloaderApp — main window (Fase 2, modular architecture).

Changes from rd.py:
- No Patreon gates, popups, or blocked consoles.
- Consoles loaded from consoles.json via console_config.
- Business logic delegated to src/services/*.
- Thread→UI communication via QueueBridge (no direct queue.put in services).
- Add Console button always visible; dialog redesigned for dual source type.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import platform
import subprocess
import sys
import threading
import tkinter
import tkinter.filedialog
import tkinter.font as tkFont
import tkinter.messagebox
import time
import urllib.parse
import webbrowser
import zipfile
from collections import deque
from pathlib import Path
from typing import Any

import customtkinter as ctk
from src.config import app_config, console_config
from src.core.constants import (
    ATTENTION_COLOR,
    CACHE_DIR,
    DOWNLOAD_DB_DIR,
    ITEMS_PER_PAGE,
    LOG_AREA_HEIGHT_PX,
    MAX_DOWNLOAD_WORKERS,
    STATUS_HISTORY_LENGTH,
)
from src.core import theme as TH
from src.core.models import Console, DownloadItem, DownloadStats, GameFile
from src.filters.game_filter import FilterConfig, apply as filter_games
from src.services import download_service, gamelist_service, history_service
from src.ui.dialogs import AddConsoleDialog, ConsoleSelectModal, CustomDialog
from src.ui.queue_bridge import QueueBridge
from src.ui.widgets import Tooltip

log = logging.getLogger(__name__)


def _get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


class LanguageManager:
    def __init__(self, app_dir: Path) -> None:
        self._app_dir = app_dir
        self.texts: dict[str, Any] = {}
        self.current_lang: str = "eng"

    def load(self, lang_code: str) -> None:
        self.current_lang = lang_code or "eng"
        path = self._app_dir / "locales" / f"{self.current_lang}.json"
        try:
            with path.open("r", encoding="utf-8") as f:
                self.texts = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.texts = {}

    def t(self, key: str, **kwargs: Any) -> str:
        text = self.texts.get(key, key.replace("_", " ").title())
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return text


class GameDownloaderApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self._app_dir = _get_app_dir()
        self._cache_dir = self._app_dir / CACHE_DIR
        self._db_dir = self._app_dir / DOWNLOAD_DB_DIR
        self._cache_dir.mkdir(exist_ok=True)
        self._db_dir.mkdir(exist_ok=True)

        self._bridge = QueueBridge()
        self._lang = LanguageManager(self._app_dir)
        self._config: dict[str, Any] = {}
        self._consoles: dict[str, Console] = {}

        self._load_config()

        # --- State ---
        self._selected_console: Console | None = None
        self._all_games: list[GameFile] = []
        self._filtered_games: list[GameFile] = []
        self._selected: set[str] = set()
        self._downloaded: set[str] = set()
        self._dest_path: Path | None = None
        self._do_force_refresh = False

        self._is_fetching = False
        self._is_preparing = False
        self._is_downloading = False
        self._is_populating = False
        self._is_faking = False

        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._dl_lock = threading.Lock()
        self._total_dl_size = 0
        self._total_dl_bytes = 0
        self._current_dl_count = 0
        self._total_dl_files = 0
        self._speed_job: str | None = None
        self._last_speed_time = 0.0
        self._last_bytes_snap = 0
        self._status_history: deque[dict[str, Any]] = deque(maxlen=STATUS_HISTORY_LENGTH)
        self._page_widgets: dict[str, Any] = {}
        self._current_page: int = 0
        self._filter_debounce: str | None = None
        self._flash_stop = threading.Event()
        self._is_flashing = False
        self._prog_bar_visible = False

        # --- tkinter vars ---
        self._console_label_var = tkinter.StringVar()
        self._search_var = tkinter.StringVar()
        self._exclude_var = tkinter.StringVar()
        self._letter_var = tkinter.StringVar(value="All")
        self._workers_var = tkinter.StringVar(
            value=str(self._config.get("max_download_workers", 2))
        )
        self._master_region_var = tkinter.StringVar(
            value=self._config.get("master_region", "All Regions")
        )
        self._1g1r_var = tkinter.BooleanVar(value=self._config.get("apply_1g1r", False))
        self._pref_region_var = tkinter.StringVar(
            value=self._config.get("preferred_region", "USA")
        )
        self._clean_var = tkinter.BooleanVar(value=self._config.get("try_to_clean", False))
        self._rem_alt_var = tkinter.BooleanVar(value=self._config.get("remove_alt_regions", False))
        self._hide_dl_var = tkinter.BooleanVar(value=False)

        # --- UI ---
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(self._lang.t("app_title"))
        self.configure(fg_color=TH.BG_DEEP)
        screen_h = self.winfo_screenheight()
        self.geometry(f"{1360}x{screen_h - 70}+0+0")

        # Typography hierarchy
        self._bold = ctk.CTkFont(family=TH.FONT_FAMILY_UI, size=TH.FONT_SIZE_LG, weight="bold")
        self._font_label = ctk.CTkFont(family=TH.FONT_FAMILY_UI, size=TH.FONT_SIZE_MD)
        self._font_sm = ctk.CTkFont(family=TH.FONT_FAMILY_UI, size=TH.FONT_SIZE_SM)
        self._font_mono = ctk.CTkFont(family=TH.FONT_FAMILY_MONO, size=TH.FONT_SIZE_SM)
        self._font_title = ctk.CTkFont(family=TH.FONT_FAMILY_UI, size=TH.FONT_SIZE_XL, weight="bold")
        self._selected_color = TH.ACCENT_DIM
        self._default_btn_color = TH.BG_SURFACE

        self._build_ui()
        self._bind_filters()

        # Restore last path
        last = self._config.get("last_download_path")
        if last:
            p = Path(last)
            if p.is_dir():
                self._dest_path = p
                self._update_dest_label()
                self._status(f"Loaded saved download path: {p}.")
            else:
                self._status("Saved download path is invalid. Please select a new folder.", error=True)
        else:
            self._status("Please select a folder to download games into.")

        if not self._dest_path:
            self.after(100, self._flash_folder_btn)

        self._toggle_controls(enabled=bool(self._dest_path))
        self.after(100, self._poll)

    # ==================================================================
    # Config
    # ==================================================================

    def _load_config(self) -> None:
        self._config = app_config.load(self._app_dir)
        self._lang.load(self._config.get("language", "eng"))
        self._consoles = console_config.load(self._app_dir)
        if self._consoles:
            self._bridge.put_status("Consoles loaded from consoles.json.")
        else:
            self._bridge.put_status("No consoles found. Use 'Add Console' to add one.")

    def _save_config(self) -> None:
        self._config["language"] = self._lang.current_lang
        self._config["master_region"] = self._master_region_var.get()
        self._config["apply_1g1r"] = self._1g1r_var.get()
        self._config["preferred_region"] = self._pref_region_var.get()
        self._config["try_to_clean"] = self._clean_var.get()
        self._config["remove_alt_regions"] = self._rem_alt_var.get()
        self._config["max_download_workers"] = self._workers_var.get()
        try:
            app_config.save(self._app_dir, self._config)
        except OSError as e:
            self._status(f"Error saving config: {e}", error=True)

    def _save_consoles(self) -> None:
        try:
            console_config.save(self._app_dir, self._consoles)
        except OSError as e:
            self._status(f"Error saving consoles: {e}", error=True)

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        main = ctk.CTkFrame(self, fg_color=TH.BG_DEEP, corner_radius=0)
        main.grid(row=0, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)  # body expands
        self._scroll = main

        self._build_top_bar(main)          # row 0
        self._build_body(main)             # row 1  (content + right sidebar)
        self._build_bottom_bar(main)       # row 2  (stats + target + progress + download)
        self._build_progress_bar(main)     # row 3  (hidden by default)
        self._build_hidden_widgets()
        self._update_ui_text()

    # ------------------------------------------------------------------
    # Top bar
    # ------------------------------------------------------------------

    def _build_top_bar(self, parent: ctk.CTkFrame) -> None:
        bar = ctk.CTkFrame(parent, corner_radius=0, fg_color=TH.BG_RAISED)
        bar.grid(row=0, column=0, sticky="new", padx=0, pady=(0, 1))
        bar.grid_columnconfigure(2, weight=1)  # search expands

        # App title
        self._title_lbl = ctk.CTkLabel(
            bar, text="Atena Emulation", font=self._font_title,
            text_color=TH.TEXT_PRIMARY,
        )
        self._title_lbl.grid(row=0, column=0, padx=(14, 12), pady=8, sticky="w")

        # Console selector (dropdown style)
        console_frame = ctk.CTkFrame(bar, fg_color="transparent")
        console_frame.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="w")

        self._console_btn = ctk.CTkButton(
            console_frame, text="", command=self._open_console_modal,
            state="disabled", font=self._bold, width=220, height=TH.HEIGHT_BTN_SECONDARY,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            hover_color=TH.BG_BORDER, border_width=1, border_color=TH.BG_BORDER,
            text_color=TH.TEXT_PRIMARY, image=None,
        )
        self._console_btn.pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            console_frame, text="\u21bb", command=self._on_refresh_clicked,
            font=ctk.CTkFont(family=TH.FONT_FAMILY_UI, size=16, weight="bold"),
            width=34, height=TH.HEIGHT_BTN_SECONDARY, state="disabled",
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            hover_color=TH.BG_BORDER, border_width=1, border_color=TH.BG_BORDER,
            text_color=TH.TEXT_SECONDARY,
        )
        self._refresh_btn.pack(side="left", padx=(4, 0))

        # Search bar (center, expands)
        self._search_entry = ctk.CTkEntry(
            bar, textvariable=self._search_var, state="disabled",
            font=self._font_label, height=TH.HEIGHT_INPUT,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            border_color=TH.BG_BORDER, text_color=TH.TEXT_PRIMARY,
            placeholder_text="\U0001f50d Search or exclude with -",
        )
        self._search_entry.grid(row=0, column=2, padx=12, pady=8, sticky="ew")

        # Settings gear (right)
        self._add_console_btn = ctk.CTkButton(
            bar, text="\u2699  Settings", command=self._open_add_console_dialog,
            font=self._font_label, width=110, height=TH.HEIGHT_BTN_SECONDARY,
            corner_radius=TH.RADIUS_SM, fg_color="transparent",
            hover_color=TH.BG_BORDER, text_color=TH.TEXT_SECONDARY,
        )
        self._add_console_btn.grid(row=0, column=3, padx=(0, 12), pady=8, sticky="e")

    # ------------------------------------------------------------------
    # Body — content list (left) + right sidebar
    # ------------------------------------------------------------------

    def _build_body(self, parent: ctk.CTkFrame) -> None:
        body = ctk.CTkFrame(parent, fg_color=TH.BG_DEEP, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)  # content expands
        body.grid_rowconfigure(0, weight=1)
        self._body = body

        self._build_content(body)    # col 0 — scrollable list
        self._build_sidebar(body)    # col 1 — right sidebar

    def _build_content(self, parent: ctk.CTkFrame) -> None:
        content = ctk.CTkFrame(parent, fg_color=TH.BG_DEEP, corner_radius=0)
        content.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Scrollable game list (no label — stats are in the bottom bar)
        self._game_list = ctk.CTkScrollableFrame(
            content, fg_color=TH.BG_DEEP,
            scrollbar_button_color=TH.BG_BORDER,
            scrollbar_button_hover_color=TH.BG_RAISED,
        )
        self._game_list.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self._game_list.grid_columnconfigure(1, weight=1)  # name col expands

        # Pagination bar
        self._pagination_bar = ctk.CTkFrame(
            content, fg_color=TH.BG_RAISED, corner_radius=0, height=36,
            border_width=1, border_color=TH.BG_BORDER,
        )
        self._pagination_bar.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        self._pagination_bar.grid_remove()  # hidden until we have pages
        self._pagination_bar.grid_columnconfigure(1, weight=1)  # center expands

        self._prev_page_btn = ctk.CTkButton(
            self._pagination_bar, text="\u25C0  Anterior", command=self._prev_page,
            font=self._font_label, width=110, height=28,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            hover_color=TH.BG_BORDER, text_color=TH.TEXT_SECONDARY,
            border_width=1, border_color=TH.BG_BORDER,
        )
        self._prev_page_btn.grid(row=0, column=0, padx=(10, 5), pady=4, sticky="w")

        self._page_indicator = ctk.CTkLabel(
            self._pagination_bar, text="", font=self._font_label,
            text_color=TH.TEXT_SECONDARY,
        )
        self._page_indicator.grid(row=0, column=1, padx=5, pady=4)

        self._next_page_btn = ctk.CTkButton(
            self._pagination_bar, text="Pr\u00F3ximo  \u25B6", command=self._next_page,
            font=self._font_label, width=110, height=28,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            hover_color=TH.BG_BORDER, text_color=TH.TEXT_SECONDARY,
            border_width=1, border_color=TH.BG_BORDER,
        )
        self._next_page_btn.grid(row=0, column=2, padx=(5, 10), pady=4, sticky="e")

        # Status log — collapsed by default
        self._status_box = ctk.CTkTextbox(
            content, wrap="word", state="disabled", height=LOG_AREA_HEIGHT_PX,
            fg_color=TH.BG_DEEP, text_color=TH.TEXT_PRIMARY, font=self._font_mono,
            border_width=1, border_color=TH.BG_BORDER,
            scrollbar_button_color=TH.BG_BORDER,
        )
        self._status_box.grid(row=2, column=0, sticky="ew", padx=0, pady=(1, 0))
        self._status_box.grid_remove()
        self._status_box.tag_config("error", foreground=TH.STATUS_COLOR_ERROR)
        self._status_box.tag_config("loading", foreground=TH.STATUS_COLOR_LOADING)
        self._status_box.tag_config("normal", foreground=TH.TEXT_PRIMARY)
        self._log_visible = False

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        """Right sidebar — filters and settings."""
        sb_width = 280
        self._sidebar = ctk.CTkFrame(
            parent, width=sb_width, fg_color=TH.SIDEBAR_BG,
            corner_radius=0, border_width=1, border_color=TH.BG_BORDER,
        )
        self._sidebar.grid(row=0, column=1, sticky="ns", padx=0, pady=0)
        self._sidebar.grid_propagate(False)

        pad = TH.SPACE_MD

        # --- Region ---
        self._region_lbl = ctk.CTkLabel(
            self._sidebar, text="", font=self._bold,
            text_color=TH.TEXT_PRIMARY, anchor="w",
        )
        self._region_lbl.pack(fill="x", padx=pad, pady=(pad, 4))

        self._region_combo = ctk.CTkComboBox(
            self._sidebar, variable=self._master_region_var,
            values=["All Regions", "USA", "Europe", "Japan"],
            state="disabled", font=self._font_label, height=TH.HEIGHT_INPUT,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_DEEP,
            border_color=TH.BG_BORDER, text_color=TH.TEXT_PRIMARY,
            button_color=TH.BG_BORDER, button_hover_color=TH.BG_SURFACE,
        )
        self._region_combo.pack(fill="x", padx=pad, pady=(0, TH.SPACE_MD))

        # --- Simultaneous Downloads ---
        self._workers_lbl = ctk.CTkLabel(
            self._sidebar, text="", font=self._bold,
            text_color=TH.TEXT_PRIMARY, anchor="w",
        )
        self._workers_lbl.pack(fill="x", padx=pad, pady=(0, 4))

        self._workers_menu = ctk.CTkOptionMenu(
            self._sidebar,
            values=[str(i) for i in range(1, MAX_DOWNLOAD_WORKERS + 1)],
            variable=self._workers_var, command=self._on_worker_change,
            font=self._font_label, height=TH.HEIGHT_INPUT,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_DEEP,
            button_color=TH.BG_BORDER, button_hover_color=TH.BG_SURFACE,
            text_color=TH.TEXT_PRIMARY,
        )
        self._workers_menu.pack(fill="x", padx=pad, pady=(0, TH.SPACE_MD))

        # --- Language ---
        self._lang_lbl = ctk.CTkLabel(
            self._sidebar, text="", font=self._bold,
            text_color=TH.TEXT_PRIMARY, anchor="w",
        )
        self._lang_lbl.pack(fill="x", padx=pad, pady=(0, 4))

        self._lang_menu = ctk.CTkOptionMenu(
            self._sidebar, values=[], command=self._on_lang_change,
            font=self._font_label, height=TH.HEIGHT_INPUT,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_DEEP,
            button_color=TH.BG_BORDER, button_hover_color=TH.BG_SURFACE,
            text_color=TH.TEXT_PRIMARY,
        )
        self._lang_menu.pack(fill="x", padx=pad, pady=(0, TH.SPACE_LG))

        # Separator
        ctk.CTkFrame(self._sidebar, height=1, fg_color=TH.BG_BORDER).pack(
            fill="x", padx=pad, pady=(0, TH.SPACE_MD),
        )

        # --- Filters ---
        self._adv_filters_lbl = ctk.CTkLabel(
            self._sidebar, text="Filters", font=self._bold,
            text_color=TH.TEXT_PRIMARY, anchor="w",
        )
        self._adv_filters_lbl.pack(fill="x", padx=pad, pady=(0, TH.SPACE_SM))

        # Hide Downloaded toggle
        self._hide_dl_cb = ctk.CTkSwitch(
            self._sidebar, text="", variable=self._hide_dl_var,
            command=lambda: self._on_filter_changed(source="other"),
            font=self._font_label, state="disabled",
            progress_color=TH.ACCENT_PRIMARY, button_color=TH.TEXT_MUTED,
            button_hover_color=TH.ACCENT_HOVER, fg_color=TH.BG_BORDER,
            text_color=TH.TEXT_SECONDARY,
        )
        self._hide_dl_cb.pack(fill="x", padx=pad, pady=(0, TH.SPACE_LG))

        # Separator
        ctk.CTkFrame(self._sidebar, height=1, fg_color=TH.BG_BORDER).pack(
            fill="x", padx=pad, pady=(0, TH.SPACE_MD),
        )

        # --- Quick actions (links style) ---
        link_style = dict(
            font=self._font_label, height=TH.HEIGHT_BTN_SM,
            corner_radius=TH.RADIUS_SM, fg_color="transparent",
            hover_color=TH.BG_BORDER, text_color=TH.TEXT_SECONDARY,
            anchor="w",
        )

        self._edit_consoles_btn = ctk.CTkButton(
            self._sidebar, text="\u270F  Edit Consoles",
            command=self._open_add_console_dialog, **link_style,
        )
        self._edit_consoles_btn.pack(fill="x", padx=pad, pady=(0, 4))

        self._gen_json_btn = ctk.CTkButton(
            self._sidebar, text="\u2B07  Export JSON",
            command=self._generate_json, **link_style,
        )
        self._gen_json_btn.pack(fill="x", padx=pad, pady=(0, TH.SPACE_MD))

    def _toggle_sidebar(self) -> None:
        """Toggle right sidebar visibility."""
        if self._sidebar.winfo_ismapped():
            self._sidebar.grid_remove()
        else:
            self._sidebar.grid()

    # ------------------------------------------------------------------
    # Bottom bar — stats | target | progress | download
    # ------------------------------------------------------------------

    def _build_bottom_bar(self, parent: ctk.CTkFrame) -> None:
        bar = ctk.CTkFrame(
            parent, fg_color=TH.BG_RAISED, corner_radius=0,
            border_width=1, border_color=TH.BG_BORDER,
        )
        bar.grid(row=2, column=0, sticky="sew", padx=0, pady=0)
        bar.grid_columnconfigure(1, weight=1)  # spacer between left and right

        # ── Left group: Target path + change button ──
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, padx=(14, 0), pady=8, sticky="w")

        ctk.CTkLabel(
            left, text="Target:", font=self._font_label,
            text_color=TH.TEXT_MUTED,
        ).pack(side="left", padx=(0, 6))

        self._dest_lbl = ctk.CTkLabel(
            left, text="", font=self._font_mono,
            text_color=TH.ACCENT_PRIMARY, anchor="w",
        )
        self._dest_lbl.pack(side="left")

        self._folder_btn = ctk.CTkButton(
            left, text="\u25BE", command=self._select_folder,
            font=self._font_label, width=28, height=22,
            corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            hover_color=TH.BG_BORDER, border_width=1, border_color=TH.BG_BORDER,
            text_color=TH.TEXT_SECONDARY,
        )
        self._folder_btn.pack(side="left", padx=(6, 0))

        # ── Center: stats + selection count ──
        center = ctk.CTkFrame(bar, fg_color="transparent")
        center.grid(row=0, column=1, padx=12, pady=8)

        self._stats_lbl = ctk.CTkLabel(
            center, text="", font=self._font_label,
            text_color=TH.TEXT_SECONDARY,
        )
        self._stats_lbl.pack(side="left", padx=(0, 6))

        self._sel_count_lbl = ctk.CTkLabel(
            center, text="", font=self._font_label,
            text_color=TH.ACCENT_PRIMARY,
        )
        self._sel_count_lbl.pack(side="left")

        # ── Right group: progress bar + download button ──
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, padx=(0, 14), pady=8, sticky="e")

        # Inline progress bar (hidden until download starts)
        self._prog_bar = ctk.CTkProgressBar(
            right, corner_radius=TH.RADIUS_SM, fg_color=TH.BG_SURFACE,
            progress_color=TH.ACCENT_PRIMARY, border_width=0,
            height=14, width=180,
        )
        self._prog_bar.set(0)
        # Start hidden — pack when download starts
        self._prog_bar_visible = False

        self._dl_btn = ctk.CTkButton(
            right, text="", command=self._start_download, state="disabled",
            font=self._bold, width=160, height=TH.HEIGHT_BTN_PRIMARY,
            corner_radius=TH.RADIUS_SM, fg_color=TH.ACCENT_PRIMARY,
            hover_color=TH.ACCENT_HOVER, text_color=TH.BG_DEEP,
        )
        self._dl_btn.pack(side="right")

    def _toggle_log(self) -> None:
        if self._log_visible:
            self._status_box.grid_remove()
            self._log_visible = False
        else:
            self._status_box.grid()
            self._log_visible = True

    # ------------------------------------------------------------------
    # Progress bar (detailed, shown during downloads)
    # ------------------------------------------------------------------

    def _build_progress_bar(self, parent: ctk.CTkFrame) -> None:
        pb = ctk.CTkFrame(
            parent, corner_radius=0, fg_color=TH.BG_RAISED,
            border_width=1, border_color=TH.BG_BORDER,
        )
        pb.grid(row=3, column=0, sticky="ew", padx=0, pady=0)
        pb.grid_remove()
        self._progress_frame = pb
        pb.grid_columnconfigure(1, weight=1)

        self._prog_title = ctk.CTkLabel(
            pb, text="", anchor="w", font=self._font_label,
            text_color=TH.TEXT_SECONDARY,
        )
        self._prog_title.grid(row=0, column=0, sticky="w", padx=(14, 10), pady=8)

        self._speed_lbl = ctk.CTkLabel(
            pb, text="", anchor="w", font=self._font_mono,
            text_color=TH.TEXT_MUTED, width=110,
        )
        self._speed_lbl.grid(row=0, column=2, sticky="ew", padx=5)

        self._dl_count_lbl = ctk.CTkLabel(
            pb, text="", anchor="w", font=self._font_mono,
            text_color=TH.TEXT_SECONDARY, width=110,
        )
        self._dl_count_lbl.grid(row=0, column=3, sticky="ew", padx=5)

        self._pause_btn = ctk.CTkButton(
            pb, text="", width=80, command=self._toggle_pause,
            state="disabled", font=self._font_label,
            height=TH.HEIGHT_BTN_SECONDARY, corner_radius=TH.RADIUS_SM,
            fg_color=TH.BG_SURFACE, hover_color=TH.BG_BORDER,
            border_width=1, border_color=TH.BG_BORDER,
            text_color=TH.TEXT_PRIMARY,
        )
        self._pause_btn.grid(row=0, column=4, sticky="e", padx=5, pady=8)

        self._cancel_btn = ctk.CTkButton(
            pb, text="", width=80, command=self._cancel,
            state="disabled", font=self._font_label,
            fg_color=TH.COLOR_DANGER, hover_color=TH.COLOR_DANGER_DIM,
            height=TH.HEIGHT_BTN_SECONDARY, corner_radius=TH.RADIUS_SM,
            text_color=TH.TEXT_PRIMARY,
        )
        self._cancel_btn.grid(row=0, column=5, sticky="e", padx=(5, 14), pady=8)

    # ------------------------------------------------------------------
    # Hidden/dummy widgets for backward compatibility
    # ------------------------------------------------------------------

    def _build_hidden_widgets(self) -> None:
        """Widgets removed from the UI but still referenced by logic.
        Will be cleaned up in a future code-removal pass."""
        ghost = ctk.CTkFrame(self, fg_color="transparent", width=0, height=0)

        self._excl_entry = ctk.CTkEntry(ghost, textvariable=self._exclude_var)
        self._pref_region_combo = ctk.CTkComboBox(
            ghost, variable=self._pref_region_var, values=["USA"],
        )
        self._1g1r_cb = ctk.CTkSwitch(
            ghost, text="", variable=self._1g1r_var, width=0,
        )
        self._clean_cb = ctk.CTkCheckBox(
            ghost, text="", variable=self._clean_var, width=0,
        )
        self._rem_alt_cb = ctk.CTkCheckBox(
            ghost, text="", variable=self._rem_alt_var, width=0,
        )
        self._fake_btn = ctk.CTkButton(ghost, text="", width=0)
        self._open_folder_btn = ctk.CTkButton(
            ghost, text="", command=self._open_folder, width=0,
        )
        self._clear_btn = ctk.CTkButton(ghost, text="", width=0)
        self._sel_all_btn = ctk.CTkButton(ghost, text="", width=0)
        self._clr_sel_btn = ctk.CTkButton(ghost, text="", width=0)
        self._clr_hist_btn = ctk.CTkButton(ghost, text="", width=0)
        self._letter_combo = ctk.CTkComboBox(ghost, variable=self._letter_var, values=["All"])
        self._search_lbl = ctk.CTkLabel(ghost, text="")
        self._letter_lbl = ctk.CTkLabel(ghost, text="")

    # ==================================================================
    # UI text update (i18n)
    # ==================================================================

    def _update_ui_text(self) -> None:
        t = self._lang.t
        self.title(t("app_title"))

        # Console selector
        if self._selected_console:
            self._console_btn.configure(text=self._selected_console.name)
        else:
            self._console_btn.configure(text=t("select_console_default"))

        # Right sidebar
        self._region_lbl.configure(text=t("master_region_label"))
        self._workers_lbl.configure(text=t("concurrent_downloads_label"))
        self._lang_lbl.configure(text=t("language_label") if "language_label" in self._lang.texts else "Language")
        self._lang_menu.configure(
            values=[t("lang_english"), t("lang_spanish"), t("lang_portuguese")],
        )
        lang_map = {"eng": t("lang_english"), "spa": t("lang_spanish"), "por": t("lang_portuguese")}
        self._lang_menu.set(lang_map.get(self._lang.current_lang, t("lang_english")))
        self._hide_dl_cb.configure(text=t("hide_downloaded_label"))
        self._adv_filters_lbl.configure(
            text=t("advanced_filters_label") if "advanced_filters_label" in self._lang.texts else "Filters",
        )

        # Bottom bar
        self._update_dest_label()
        self._update_sel_count()
        self._dl_btn.configure(text=t("download_button"))
        self._prog_title.configure(text=t("progress_label"))
        self._pause_btn.configure(text=t("pause_button"))
        self._cancel_btn.configure(text=t("cancel_button"))
        self._update_game_list()

    # ==================================================================
    # Filter bindings
    # ==================================================================

    def _bind_filters(self) -> None:
        self._search_var.trace_add("write", lambda *_: self._on_filter_changed(source="other"))
        self._exclude_var.trace_add("write", lambda *_: self._on_filter_changed(source="other"))
        self._letter_var.trace_add("write", lambda *_: self._on_filter_changed(source="alpha"))
        self._1g1r_var.trace_add("write", self._on_1g1r_toggle)
        self._master_region_var.trace_add("write", self._on_master_region_change)
        self._pref_region_var.trace_add("write", lambda *_: self._on_filter_changed(source="other"))

    def _on_filter_changed(self, *_args: Any, source: str = "other") -> None:
        if self._filter_debounce:
            self.after_cancel(self._filter_debounce)
        delay = 50 if source == "alpha" else 300
        self._filter_debounce = self.after(delay, self._update_game_list)

    def _on_1g1r_toggle(self, *_: Any) -> None:
        enabled = self._1g1r_var.get()
        state = "readonly" if enabled and self._master_region_var.get() == "All Regions" else "disabled"
        if self._pref_region_combo.winfo_exists():
            self._pref_region_combo.configure(state=state)
        self._on_filter_changed(source="other")

    def _on_master_region_change(self, *_: Any) -> None:
        is_active = self._master_region_var.get() != "All Regions"
        can_enable = self._rem_alt_cb.cget("state") in ("normal", "readonly")
        if self._rem_alt_cb.winfo_exists():
            self._rem_alt_cb.configure(state="disabled" if is_active or not can_enable else "normal")
        if self._pref_region_combo.winfo_exists():
            new_st = "disabled" if is_active or not self._1g1r_var.get() or not can_enable else "readonly"
            self._pref_region_combo.configure(state=new_st)
        self._on_filter_changed(source="other")

    # ==================================================================
    # Folder selection
    # ==================================================================

    def _select_folder(self) -> None:
        if self._busy():
            return
        path_str = tkinter.filedialog.askdirectory(title=self._lang.t("select_download_folder"))
        if not path_str:
            self._status("Folder selection cancelled.")
            return
        self._flash_stop.set()
        self._dest_path = Path(path_str)
        self._config["last_download_path"] = str(self._dest_path)
        self._save_config()
        self._update_dest_label()
        self._status(f"Download folder set to: {self._dest_path}")
        self._all_games = []
        self._filtered_games = []
        self._update_game_list(clear=True)
        self._toggle_controls(enabled=True)

    def _update_dest_label(self) -> None:
        if not self._dest_path:
            self._dest_lbl.configure(text="...")
            return
        s = str(self._dest_path)
        if len(s) > 60:
            parts = self._dest_path.parts
            s = os.path.join(parts[0], "...", *parts[-2:]) if len(parts) > 3 else s[:25] + "..." + s[-30:]
        self._dest_lbl.configure(text=s)

    # ==================================================================
    # Console selection
    # ==================================================================

    def _open_console_modal(self) -> None:
        ConsoleSelectModal(
            parent=self,
            title=self._lang.t("select_console_title"),
            consoles=self._consoles,
            on_select=self._on_console_selected,
        )

    def _on_console_selected(self, name: str) -> None:
        c = self._consoles.get(name)
        if not c:
            return
        if self._busy():
            self._status("Please wait for the current operation to finish.", error=True)
            return
        self._selected_console = c
        self._console_btn.configure(text=name)
        self._clear_selection(update_status=False)
        self._all_games = []
        self._filtered_games = []
        self._update_game_list(clear=True)
        self._is_fetching = True
        self._toggle_controls(enabled=False)
        self._stats_lbl.configure(
            text=self._lang.t("game_list_label_loading", console_name=name)
        )
        threading.Thread(
            target=self._fetch_gamelist_thread,
            args=(c, self._do_force_refresh),
            daemon=True,
        ).start()
        self._do_force_refresh = False

    def _on_refresh_clicked(self) -> None:
        if self._selected_console:
            self._do_force_refresh = True
            self._on_console_selected(self._selected_console.name)

    # ==================================================================
    # Add / Edit Console dialog
    # ==================================================================

    def _open_add_console_dialog(self) -> None:
        AddConsoleDialog(
            parent=self,
            lang=self._lang.t,
            bold_font=self._bold,
            consoles=self._consoles,
            on_action=self._on_console_action,
        )

    def _on_console_action(self, action: str, console: Console) -> None:
        """Callback from AddConsoleDialog — processes each action while dialog stays open."""
        if action == "delete":
            from src.core import credential_store
            credential_store.delete(console.name)
            if console.name in self._consoles:
                del self._consoles[console.name]
            self._save_consoles()
            self._status(f"Deleted console: {console.name}", error=True)
            if self._selected_console and self._selected_console.name == console.name:
                self._selected_console = None
                self._console_btn.configure(text=self._lang.t("select_console_default"))
                self._all_games = []
                self._filtered_games = []
                self._update_game_list(clear=True)
        else:
            is_new = action == "add"
            url_changed = False
            if not is_new:
                # Console was already updated in self._consoles by the dialog;
                # compare against the newly-saved object's prior state if needed
                existing = self._consoles.get(console.name)
                if existing and existing is not console:
                    url_changed = (
                        existing.url != console.url
                        or existing.identifier != console.identifier
                    )
            self._consoles[console.name] = console
            self._save_consoles()
            self._status(
                f"{'Added' if is_new else 'Updated'} console: {console.name}"
            )
            if url_changed and self._selected_console and self._selected_console.name == console.name:
                self._do_force_refresh = True
                self._on_console_selected(console.name)
            elif not self._selected_console:
                self._on_console_selected(console.name)

    # ==================================================================
    # Gamelist thread
    # ==================================================================

    def _fetch_gamelist_thread(self, console: Console, force: bool) -> None:
        log.info("Fetching gamelist for '%s' (force=%s)", console.name, force)
        t0 = time.monotonic()
        try:
            games = gamelist_service.fetch(
                console=console,
                cache_dir=self._cache_dir,
                on_status=self._bridge.make_status_cb(),
                force_refresh=force,
            )
            elapsed = time.monotonic() - t0
            log.info("Fetched %d games for '%s' in %.2fs", len(games), console.name, elapsed)
            self._bridge.put_gamelist_ok(console.name, games)
        except Exception as exc:
            log.exception("Failed to fetch gamelist for '%s'", console.name)
            self._bridge.put_gamelist_err(str(exc))

    def _process_gamelist_result(self, data: dict[str, Any]) -> None:
        self._is_fetching = False
        if data.get("success"):
            console_name: str = data["console"]
            games: list[GameFile] = data["games"]
            self._all_games = games
            self._downloaded = history_service.load(self._db_dir, console_name)
            log.info("Processing gamelist: %d games, %d already downloaded", len(games), len(self._downloaded))
            self._status(f"Loaded {len(games)} games for {console_name}.")
        else:
            log.warning("Gamelist load failed: %s", data.get('error', 'Unknown'))
            self._status(f"Error: {data.get('error', 'Unknown')}", error=True)
            self._all_games = []
        self._update_game_list(clear=True)
        self._toggle_controls(enabled=True)

    # ==================================================================
    # Game list display
    # ==================================================================

    def _update_game_list(self, clear: bool = False) -> None:
        t0 = time.monotonic()
        if clear:
            self._current_page = 0

        # --- Filter ---
        t_filter = time.monotonic()
        cfg = FilterConfig(
            search_keywords=[k.strip() for k in self._search_var.get().lower().strip().split(",") if k.strip()],
            exclude_keywords=[k.strip() for k in self._exclude_var.get().lower().strip().split(",") if k.strip()],
            try_to_clean=self._clean_var.get(),
            letter=self._letter_var.get(),
            master_region=self._master_region_var.get(),
            apply_1g1r=self._1g1r_var.get(),
            preferred_region=self._pref_region_var.get(),
            remove_alt_regions=self._rem_alt_var.get(),
            hide_downloaded=self._hide_dl_var.get(),
            downloaded=self._downloaded,
        )
        self._filtered_games = filter_games(self._all_games, cfg)
        count = len(self._filtered_games)
        log.debug("Filter applied: %d -> %d games in %.3fs", len(self._all_games), count, time.monotonic() - t_filter)

        self._status(f"Filters updated. {count} matching games.")

        # --- Stats ---
        con_name = self._selected_console.name if self._selected_console else ""
        if count > 0:
            tot_sz = sum(g.size_bytes for g in self._filtered_games)
            self._stats_lbl.configure(
                text=f"{count} games  \u2022  {self._fmt_bytes(tot_sz)}",
            )
        elif con_name:
            self._stats_lbl.configure(text="0 games")
        else:
            self._stats_lbl.configure(text="")

        # --- Render current page ---
        self._render_current_page()
        log.debug("_update_game_list completed in %.3fs", time.monotonic() - t0)

    def _render_current_page(self) -> None:
        """Clear the list and render only the current page of filtered games."""
        t0 = time.monotonic()

        # Destroy existing widgets
        for w in self._game_list.winfo_children():
            w.destroy()
        self._page_widgets = {}

        # Reset scroll position
        canvas = getattr(self._game_list, "_parent_canvas", None)
        if canvas and canvas.winfo_exists():
            canvas.yview_moveto(0)

        count = len(self._filtered_games)
        if not count:
            self._pagination_bar.grid_remove()
            self._show_empty_list()
            self._toggle_controls(enabled=True)
            return

        # Pagination math
        total_pages = max(1, (count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self._current_page = max(0, min(self._current_page, total_pages - 1))
        start = self._current_page * ITEMS_PER_PAGE
        end = min(start + ITEMS_PER_PAGE, count)
        page_slice = self._filtered_games[start:end]

        log.debug("Rendering page %d/%d (items %d-%d of %d)", self._current_page + 1, total_pages, start, end, count)

        # Configure grid
        self._game_list.grid_columnconfigure(0, weight=0, minsize=40)   # checkbox
        self._game_list.grid_columnconfigure(1, weight=1)               # name
        self._game_list.grid_columnconfigure(2, weight=0, minsize=70)   # region
        self._game_list.grid_columnconfigure(3, weight=0, minsize=90)   # size

        # Render rows
        row_a = TH.BG_DEEP
        row_b = TH.BG_SURFACE
        sel_bg = TH.ACCENT_DIM

        for i, g in enumerate(page_slice):
            is_sel = g.filename in self._selected
            is_dl = g.filename in self._downloaded
            row_bg = sel_bg if is_sel else (row_a if i % 2 == 0 else row_b)

            # Checkbox
            cb_var = tkinter.BooleanVar(value=is_sel)
            cb = ctk.CTkCheckBox(
                self._game_list, text="", variable=cb_var,
                command=lambda fn=g.filename: self._toggle_row(fn),
                width=20, checkbox_width=20, checkbox_height=20,
                fg_color=TH.ACCENT_PRIMARY, hover_color=TH.ACCENT_HOVER,
                border_color=TH.BG_BORDER,
            )
            cb.grid(row=i, column=0, padx=(10, 4), pady=1, sticky="w")

            # Game name
            name_text = g.filename
            name_color = TH.TEXT_MUTED if is_dl else TH.TEXT_PRIMARY
            name_lbl = ctk.CTkLabel(
                self._game_list, text=name_text, font=self._font_label,
                text_color=name_color, anchor="w", fg_color=row_bg,
                corner_radius=0, height=36,
            )
            name_lbl.grid(row=i, column=1, padx=0, pady=1, sticky="ew")

            # Region badge
            region = self._extract_region(g.filename)
            if region:
                badge_colors = {
                    "USA": TH.ACCENT_PRIMARY,
                    "EUR": "#6C7BCC",
                    "JPN": "#CC6C6C",
                }
                badge = ctk.CTkLabel(
                    self._game_list, text=region,
                    font=ctk.CTkFont(family=TH.FONT_FAMILY_UI, size=11, weight="bold"),
                    text_color=TH.BG_DEEP, fg_color=badge_colors.get(region, TH.BG_BORDER),
                    corner_radius=4, height=22, width=42,
                )
                badge.grid(row=i, column=2, padx=6, pady=1)
            else:
                ctk.CTkLabel(
                    self._game_list, text="", height=36,
                    fg_color="transparent",
                ).grid(row=i, column=2, padx=6, pady=1)

            # Size
            size_lbl = ctk.CTkLabel(
                self._game_list, text=g.size_str, font=self._font_mono,
                text_color=TH.TEXT_MUTED, anchor="e", height=36,
            )
            size_lbl.grid(row=i, column=3, padx=(4, 14), pady=1, sticky="e")

            # Bind click on row labels
            for w in (name_lbl, size_lbl):
                w.bind("<Button-1>", lambda e, fn=g.filename: self._toggle_row(fn))
                w.bind("<Button-3>", lambda e, fn=g.filename: self._show_context_menu(e, fn))

            # Store refs
            self._page_widgets[g.filename] = (cb, cb_var, name_lbl, i)

            if is_dl:
                Tooltip(name_lbl, text=self._lang.t("tooltip_already_downloaded"))

        # Update pagination bar
        if total_pages > 1:
            self._page_indicator.configure(
                text=f"P\u00E1gina {self._current_page + 1} / {total_pages}"
            )
            self._prev_page_btn.configure(
                state="normal" if self._current_page > 0 else "disabled"
            )
            self._next_page_btn.configure(
                state="normal" if self._current_page < total_pages - 1 else "disabled"
            )
            self._pagination_bar.grid()
        else:
            self._pagination_bar.grid_remove()

        self._toggle_controls(enabled=True)
        elapsed = time.monotonic() - t0
        log.info("Page rendered: %d items in %.3fs", len(page_slice), elapsed)

    # ------------------------------------------------------------------
    # Pagination navigation
    # ------------------------------------------------------------------

    def _next_page(self) -> None:
        total_pages = max(1, (len(self._filtered_games) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._render_current_page()

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

    @staticmethod
    def _extract_region(filename: str) -> str:
        """Extract region tag from ROM filename."""
        fn = filename.lower()
        if "(usa)" in fn or "(us)" in fn:
            return "USA"
        if "(europe)" in fn or "(eur)" in fn:
            return "EUR"
        if "(japan)" in fn or "(jp)" in fn:
            return "JPN"
        return ""

    def _show_empty_list(self) -> None:
        t = self._lang.t
        con = self._selected_console.name if self._selected_console else ""
        msg: str | None = None
        if self._is_fetching:
            msg = t("game_list_label_loading", console_name=con)
        elif not self._dest_path:
            msg = t("game_list_empty_select_folder")
        elif not self._filtered_games and con:
            has_filter = any([
                self._search_var.get(),
                self._master_region_var.get() != "All Regions",
            ])
            msg = t("game_list_empty_no_match") if has_filter else t("game_list_empty_no_files")
        else:
            msg = t("game_list_empty_select_console_prompt")
        if msg:
            ctk.CTkLabel(
                self._game_list, text=msg, font=self._font_title,
                text_color=TH.TEXT_MUTED,
            ).grid(row=0, column=0, columnspan=4, pady=80, sticky="ew")

    # ==================================================================
    # Selection
    # ==================================================================

    def _toggle_row(self, filename: str) -> None:
        if self._busy():
            return
        if filename in self._selected:
            self._selected.discard(filename)
            is_sel = False
        else:
            self._selected.add(filename)
            is_sel = True

        widget_data = self._page_widgets.get(filename)
        if widget_data:
            cb, cb_var, name_lbl, row_idx = widget_data
            cb_var.set(is_sel)
            row_bg = TH.ACCENT_DIM if is_sel else (TH.BG_DEEP if row_idx % 2 == 0 else TH.BG_SURFACE)
            name_lbl.configure(fg_color=row_bg)
        self._update_sel_count()

    def _select_all(self) -> None:
        if self._busy():
            return
        for g in self._filtered_games:
            self._selected.add(g.filename)
        for fn, data in self._page_widgets.items():
            if fn in self._selected:
                cb, cb_var, name_lbl, _ = data
                cb_var.set(True)
                name_lbl.configure(fg_color=TH.ACCENT_DIM)
        self._update_sel_count()
        self._status(f"Selected {len(self._filtered_games)} games.")

    def _clear_selection(self, update_status: bool = True) -> None:
        if self._busy() and update_status:
            self._status("Cannot clear selection during operation.", error=True)
            return
        count = len(self._selected)
        on_page = self._selected & set(self._page_widgets)
        self._selected.clear()
        for fn in on_page:
            data = self._page_widgets.get(fn)
            if data:
                cb, cb_var, name_lbl, row_idx = data
                cb_var.set(False)
                name_lbl.configure(
                    fg_color=TH.BG_DEEP if row_idx % 2 == 0 else TH.BG_SURFACE,
                )
        self._update_sel_count()
        if update_status and count:
            self._status(f"Cleared {count} selected games.")

    def _update_sel_count(self) -> None:
        n = len(self._selected)
        if n:
            tot_sz = sum(g.size_bytes for g in self._all_games if g.filename in self._selected)
            text = f"{n} selected  \u2022  {self._fmt_bytes(tot_sz)}"
        else:
            text = ""
        self._sel_count_lbl.configure(text=text)
        # Only update download button state (lightweight, no layout thrashing)
        can_act = n > 0 and not self._busy() and self._dest_path is not None
        self._dl_btn.configure(
            state="normal" if can_act else "disabled",
            fg_color=TH.ACCENT_PRIMARY if can_act else TH.BG_SURFACE,
            hover_color=TH.ACCENT_HOVER if can_act else TH.BG_BORDER,
            text_color=TH.BG_DEEP if can_act else TH.TEXT_MUTED,
        )

    def _clear_history(self) -> None:
        if not self._selected_console:
            return
        history_service.clear(self._db_dir, self._selected_console.name)
        self._downloaded = set()
        self._status("Download history cleared.")
        self._update_game_list(clear=True)

    # ==================================================================
    # Search helpers
    # ==================================================================

    def _clear_search(self) -> None:
        self._search_var.set("")
        self._exclude_var.set("")
        self._letter_var.set("All")
        self._master_region_var.set("All Regions")
        self._1g1r_var.set(False)
        self._clean_var.set(False)
        self._rem_alt_var.set(False)
        self._hide_dl_var.set(False)

    # ==================================================================
    # Download flow
    # ==================================================================

    def _start_download(self) -> None:
        if not self._dest_path or not self._selected_console or not self._selected:
            return
        games = [g for g in self._all_games if g.filename in self._selected]
        dest = self._dest_for_console(self._selected_console)
        if not dest:
            self._status("Download folder not set.", error=True)
            return
        self._is_preparing = True
        self._cancel_event.clear()
        self._pause_event.clear()
        self._toggle_controls(enabled=False)
        self._prog_title.configure(text=self._lang.t("progress_label_preparing"))
        self._prog_bar.set(0)
        self._cancel_btn.configure(state="normal")
        threading.Thread(
            target=self._prepare_thread,
            args=(self._selected_console, games, dest),
            daemon=True,
        ).start()

    def _prepare_thread(
        self,
        console: Console,
        games: list[GameFile],
        dest: Path,
    ) -> None:
        try:
            items = download_service.prepare(
                console=console,
                games=games,
                download_path=dest,
                on_progress=self._bridge.make_prep_progress_cb(),
                on_status=self._bridge.make_status_cb(),
                cancel_event=self._cancel_event,
                pause_event=self._pause_event,
            )
            self._bridge.put_prepare_complete(items)
        except Exception as exc:
            self._bridge.put_status(f"Prepare failed: {exc}", error=True)

    def _start_download_phase(self, items: list[DownloadItem]) -> None:
        pending = [i for i in items if i.status == "pending"]
        skipped = sum(1 for i in items if i.status == "skipped")
        if not pending:
            msg = self._lang.t("prep_complete_text", skipped_count=skipped)
            self._status(msg)
            self._toggle_controls(enabled=True)
            self._prog_bar.set(0)
            self._prog_title.configure(text=self._lang.t("progress_label"))
            CustomDialog(self, title=self._lang.t("download_complete_title"), message=msg, buttons={self._lang.t("ok_button"): True}).wait_for_response()
            return
        self._is_downloading = True
        self._total_dl_files = len(pending)
        self._current_dl_count = 0
        self._total_dl_bytes = 0
        self._total_dl_size = 0
        self._prog_title.configure(text=self._lang.t("progress_label_downloading"))
        self._prog_bar.set(0)
        self._pause_btn.configure(text=self._lang.t("pause_button"), state="normal")
        self._cancel_btn.configure(state="normal")
        self._update_dl_counter()
        self._last_speed_time = 0.0
        self._last_bytes_snap = 0
        if self._speed_job:
            self.after_cancel(self._speed_job)
        self._update_speed()
        try:
            workers = int(self._workers_var.get())
        except (ValueError, TypeError):
            workers = 1
        console = self._selected_console
        threading.Thread(
            target=download_service.download,
            kwargs=dict(
                items=items,
                console=console,
                db_dir=self._db_dir,
                on_bytes=self._bridge.make_bytes_cb(),
                on_file_done=self._bridge.make_file_done_cb(),
                on_complete=self._bridge.make_complete_cb(),
                on_status=self._bridge.make_status_cb(),
                cancel_event=self._cancel_event,
                pause_event=self._pause_event,
                workers=workers,
            ),
            daemon=True,
        ).start()

    # ==================================================================
    # Fake ROMs
    # ==================================================================

    def _start_fake_roms(self) -> None:
        if self._busy() or not self._dest_path or not self._selected_console or not self._selected:
            return
        dest = self._dest_for_console(self._selected_console)
        if not dest:
            return
        n = len(self._selected)
        dlg = CustomDialog(
            self,
            title=self._lang.t("confirm_action_title"),
            message=self._lang.t("fake_roms_confirm_message", num_selected=n, folder=dest),
            buttons={self._lang.t("proceed_button"): True, self._lang.t("cancel_button"): False},
        )
        if not dlg.wait_for_response():
            return
        self._is_faking = True
        self._cancel_event.clear()
        self._toggle_controls(enabled=False)
        self._prog_title.configure(text=self._lang.t("progress_label_creating_fakes"))
        self._prog_bar.set(0)
        self._cancel_btn.configure(state="normal")
        threading.Thread(
            target=self._fake_roms_thread,
            args=(list(self._selected), dest),
            daemon=True,
        ).start()

    def _fake_roms_thread(self, filenames: list[str], dest: Path) -> None:
        total = len(filenames)
        created = skipped = errors = 0
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._bridge.put_status(f"Could not create folder {dest}: {e}", error=True)
            self._bridge.put_fake_complete(0, 0, total)
            return
        prog_cb = self._bridge.make_fake_progress_cb()
        for i, fn in enumerate(filenames):
            if self._cancel_event.is_set():
                break
            path = dest / fn
            if path.exists():
                skipped += 1
            else:
                try:
                    with zipfile.ZipFile(path, "w"):
                        pass
                    created += 1
                except (OSError, IOError) as e:
                    self._bridge.put_status(f"Error creating fake ROM {fn}: {e}", error=True)
                    errors += 1
            prog_cb(i + 1, total)
        if self._cancel_event.is_set():
            self.after(100, self._reset_after_cancel, "Fake ROM creation cancelled.")
        else:
            self._bridge.put_fake_complete(created, skipped, errors)

    # ==================================================================
    # Generate JSON export
    # ==================================================================

    def _generate_json(self) -> None:
        if not self._selected or not self._selected_console:
            self._status("No games selected.", error=True)
            return
        directory = tkinter.filedialog.askdirectory(
            title=self._lang.t("select_folder_for_json_title")
        )
        if not directory:
            return
        console_name = self._selected_console.name
        games_list = [{"rom_name": fn} for fn in sorted(self._selected)]
        covers: dict[str, str] = {
            pathlib.Path(fn).stem: f"images/covers/{console_name}/{pathlib.Path(fn).stem}.jpg"
            for fn in sorted(self._selected)
        }
        try:
            base = pathlib.Path(directory)
            with (base / "_games.json").open("w", encoding="utf-8") as f:
                json.dump(games_list, f, indent=2)
            with (base / "_covers.json").open("w", encoding="utf-8") as f:
                json.dump(covers, f, indent=4)
            self._status(f"Generated _games.json and _covers.json in: {directory}")
        except OSError as e:
            self._status(f"Error saving JSON files: {e}", error=True)

    # ==================================================================
    # Pause / Cancel / Reset
    # ==================================================================

    def _toggle_pause(self) -> None:
        t = self._lang.t
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._pause_btn.configure(text=t("pause_button"))
            self._status("Operation resumed.")
        else:
            self._pause_event.set()
            self._pause_btn.configure(text=t("resume_button"))
            self._status("Operation paused.")

    def _cancel(self) -> None:
        if not self._cancel_event.is_set():
            self._cancel_event.set()
            self._pause_event.clear()
            self._status("Cancelling operation...", error=True)

    def _reset_after_cancel(self, message: str = "Operation cancelled.") -> None:
        self._is_downloading = False
        self._is_preparing = False
        self._is_faking = False
        self._cancel_event.clear()
        self._pause_event.clear()
        self._prog_bar.set(0)
        self._prog_title.configure(text=self._lang.t("progress_label"))
        self._pause_btn.configure(state="disabled")
        self._cancel_btn.configure(state="disabled")
        self._speed_lbl.configure(text="")
        self._dl_count_lbl.configure(text="")
        if self._speed_job:
            self.after_cancel(self._speed_job)
            self._speed_job = None
        self._toggle_controls(enabled=True)
        self._status(message, error=True)

    # ==================================================================
    # Folder helpers
    # ==================================================================

    def _dest_for_console(self, console: Console) -> Path | None:
        if not self._dest_path:
            return None
        if console.path:
            p = Path(console.path)
            if p.is_dir():
                return p
        return self._dest_path / console.name

    def _open_folder(self) -> None:
        if not self._dest_path:
            return
        path = (
            self._dest_for_console(self._selected_console)
            if self._selected_console
            else self._dest_path
        )
        if not path:
            return
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            tkinter.messagebox.showerror("Error", f"Could not open folder:\n{e}")

    # ==================================================================
    # Queue poll (replaces check_status_queue)
    # ==================================================================

    def _poll(self) -> None:
        try:
            while True:
                try:
                    msg_type, data = self._bridge.q.get_nowait()
                except Exception:
                    break
                try:
                    self._handle_message(msg_type, data)
                except Exception:
                    log.exception("Error handling queue message '%s'", msg_type)
                self._bridge.q.task_done()
        except Exception:
            log.exception("Unexpected error in _poll")
        self.after(100, self._poll)

    def _handle_message(self, msg_type: str, data: Any) -> None:
        t = self._lang.t
        if msg_type == "status":
            self._status(data.get("message", ""), error=data.get("error", False))

        elif msg_type == "gamelist_load_complete":
            self._process_gamelist_result(data)

        elif msg_type in ("prep_progress", "fake_progress"):
            if (self._is_preparing or self._is_faking) and self._prog_bar.winfo_ismapped():
                self._prog_bar.set(data.get("percent", 0) / 100.0)

        elif msg_type == "progress_update":
            if self._is_downloading:
                with self._dl_lock:
                    self._total_dl_bytes += data.get("add_bytes", 0)
                    if data.get("add_total_size", 0) > 0:
                        self._total_dl_size += data["add_total_size"]
                if self._total_dl_size > 0:
                    pct = min(100, int(self._total_dl_bytes / self._total_dl_size * 100))
                elif self._total_dl_files > 0:
                    pct = min(100, int(self._current_dl_count / self._total_dl_files * 100))
                else:
                    pct = 0
                self._prog_bar.set(pct / 100.0)

        elif msg_type == "file_complete":
            if data.get("success"):
                with self._dl_lock:
                    self._current_dl_count += 1
                    self._downloaded.add(data["item"].game.filename)
            self._update_dl_counter()

        elif msg_type == "prepare_complete":
            self._is_preparing = False
            items: list[DownloadItem] = data.get("items", [])
            if self._cancel_event.is_set():
                self._reset_after_cancel("Preparation cancelled.")
                return
            self._start_download_phase(items)

        elif msg_type == "download_complete":
            if self._speed_job:
                self.after_cancel(self._speed_job)
                self._speed_job = None
            self._speed_lbl.configure(text="")
            self._dl_count_lbl.configure(text="")
            self._is_downloading = False
            self._toggle_controls(enabled=True)
            self._pause_event.clear()
            self._cancel_event.clear()
            self._prog_bar.set(0)
            self._prog_title.configure(text=t("progress_label"))
            stats: DownloadStats = data
            summary = t(
                "download_complete_summary_message",
                downloaded=stats.downloaded,
                skipped=stats.skipped,
                errors=stats.failed,
                total_size=self._fmt_bytes(stats.total_bytes),
            )
            self._status(
                f"Done — downloaded: {stats.downloaded}, skipped: {stats.skipped}, failed: {stats.failed}",
                error=stats.failed > 0,
            )
            CustomDialog(self, title=t("download_complete_title"), message=summary, buttons={t("ok_button"): True}).wait_for_response()
            self._update_game_list(clear=True)

        elif msg_type == "download_cancelled":
            self._reset_after_cancel("Download cancelled.")

        elif msg_type == "fake_creation_complete":
            self._is_faking = False
            self._toggle_controls(enabled=True)
            self._pause_event.clear()
            self._cancel_event.clear()
            self._prog_bar.set(0)
            self._prog_title.configure(text=t("progress_label"))
            summary = t(
                "fake_roms_complete_summary",
                created=data.get("created_count", 0),
                skipped=data.get("skipped_count", 0),
                errors=data.get("error_count", 0),
            )
            CustomDialog(self, title=t("operation_complete_title"), message=summary, buttons={t("ok_button"): True}).wait_for_response()

    # ==================================================================
    # Controls enable/disable
    # ==================================================================

    def _toggle_controls(self, enabled: bool = True) -> None:
        op = self._busy()
        core = enabled and not op
        has_dest = self._dest_path is not None
        list_ok = core and has_dest
        ls = "normal" if list_ok else "disabled"
        try:
            # Top bar
            self._folder_btn.configure(state="disabled" if op else "normal")
            self._add_console_btn.configure(state="disabled" if op else "normal")
            self._console_btn.configure(state="normal" if list_ok else "disabled")
            self._search_entry.configure(state=ls)
            is_con = self._selected_console is not None
            self._refresh_btn.configure(
                state="normal" if ls == "normal" and is_con else "disabled",
            )

            # Right sidebar
            self._region_combo.configure(state=ls)
            self._workers_menu.configure(state="normal" if core else "disabled")
            self._hide_dl_cb.configure(state=ls)

            # Bottom bar — download button
            can_act = ls == "normal" and bool(self._selected)
            self._dl_btn.configure(
                state="normal" if can_act else "disabled",
                fg_color=TH.ACCENT_PRIMARY if can_act else TH.BG_SURFACE,
                hover_color=TH.ACCENT_HOVER if can_act else TH.BG_BORDER,
                text_color=TH.BG_DEEP if can_act else TH.TEXT_MUTED,
            )

            # Progress visibility
            cancellable = self._is_preparing or self._is_downloading or self._is_faking
            if cancellable and not self._prog_bar_visible:
                self._prog_bar.pack(side="right", padx=(0, 10), fill="x", expand=True)
                self._prog_bar_visible = True
                self._progress_frame.grid()
            elif not cancellable and not op and self._prog_bar_visible:
                self._prog_bar.pack_forget()
                self._prog_bar_visible = False
                self._progress_frame.grid_remove()
            self._pause_btn.configure(state="normal" if cancellable else "disabled")
            self._cancel_btn.configure(state="normal" if cancellable else "disabled")
        except Exception:
            log.debug("Error toggling UI controls", exc_info=True)

    def _busy(self) -> bool:
        return (
            self._is_fetching
            or self._is_preparing
            or self._is_downloading
            or self._is_populating
            or self._is_faking
        )

    # ==================================================================
    # Context menu
    # ==================================================================

    def _show_context_menu(self, event: tkinter.Event, filename: str) -> None:
        was_selected = filename in self._selected
        if not was_selected:
            self._toggle_row(filename)
        menu = tkinter.Menu(self, tearoff=0)
        font = tkFont.Font(family="sans-serif", size=11, weight="bold")
        t = self._lang.t
        menu.add_command(
            label=t("context_menu_search_google"),
            command=lambda: self._web_search(filename, "google", was_selected),
            font=font,
        )
        menu.add_separator()
        menu.add_command(
            label=t("context_menu_search_lb"),
            command=lambda: self._web_search(filename, "launchbox", was_selected),
            font=font,
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _web_search(self, filename: str, engine: str, was_selected: bool) -> None:
        import re
        stem = pathlib.Path(filename).stem
        cleaned = re.sub(r"\s*\([^)]*\)", "", stem).strip()
        con_name = self._selected_console.name if self._selected_console else ""
        base = f"{cleaned} {con_name}".strip()
        query = f"site:gamesdb.launchbox-app.com {base}" if engine == "launchbox" else base
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        self._status(f"Searching: {query}")
        webbrowser.open_new_tab(url)
        if not was_selected:
            self._toggle_row(filename)

    # ==================================================================
    # Speed / counter display
    # ==================================================================

    def _update_speed(self) -> None:
        if not self._is_downloading:
            self._speed_lbl.configure(text="")
            self._speed_job = None
            return
        if self._pause_event.is_set():
            self._speed_lbl.configure(text=self._lang.t("pause_button"))
            self._last_speed_time = 0.0
            self._speed_job = self.after(500, self._update_speed)
            return
        now = time.time()
        if self._last_speed_time == 0.0:
            self._last_speed_time = now
            with self._dl_lock:
                self._last_bytes_snap = self._total_dl_bytes
            self._speed_lbl.configure(text="...")
        else:
            delta_t = now - self._last_speed_time
            if delta_t >= 1.0:
                with self._dl_lock:
                    cur = self._total_dl_bytes
                speed = (cur - self._last_bytes_snap) / delta_t
                self._speed_lbl.configure(text=self._fmt_speed(speed))
                self._last_bytes_snap = cur
                self._last_speed_time = now
        self._speed_job = self.after(1000, self._update_speed)

    def _update_dl_counter(self) -> None:
        if self._is_downloading and self._total_dl_files > 0:
            text = self._lang.t(
                "progress_downloading_counter",
                current=self._current_dl_count,
                total=self._total_dl_files,
            )
            self._dl_count_lbl.configure(text=text)
        else:
            self._dl_count_lbl.configure(text="")

    # ==================================================================
    # Language
    # ==================================================================

    def _on_lang_change(self, choice: str) -> None:
        t = self._lang.t
        lang_map = {
            t("lang_english"): "eng",
            t("lang_spanish"): "spa",
            t("lang_portuguese"): "por",
        }
        code = lang_map.get(choice, "eng")
        self._lang.load(code)
        self._config["language"] = code
        self._save_config()
        self._update_ui_text()

    def _on_worker_change(self, _: str) -> None:
        self._save_config()

    # ==================================================================
    # Flash folder button
    # ==================================================================

    def _flash_folder_btn(self) -> None:
        if self._flash_stop.is_set() or not self._folder_btn.winfo_exists():
            if self._folder_btn.winfo_exists():
                self._folder_btn.configure(fg_color=self._default_btn_color)
            return
        color = self._default_btn_color if self._is_flashing else ATTENTION_COLOR
        self._folder_btn.configure(fg_color=color)
        self._is_flashing = not self._is_flashing
        self.after(800, self._flash_folder_btn)

    # ==================================================================
    # Status log
    # ==================================================================

    def _status(self, message: str, error: bool = False) -> None:
        if not hasattr(self, "_status_box") or not self._status_box.winfo_exists():
            return
        busy = self._busy()
        prefix = "PLEASE WAIT: " if busy and not error else ""
        tag = "error" if error else ("loading" if busy else "normal")
        ts = time.strftime("%H:%M:%S")
        entry = {"text": f"[{ts}] {prefix}{message}\n", "tag": tag}
        self._status_history.append(entry)
        try:
            self._status_box.configure(state="normal")
            self._status_box.delete("1.0", "end")
            for item in self._status_history:
                self._status_box.insert("1.0", item["text"], item["tag"])
            self._status_box.configure(state="disabled")
        except Exception:
            log.debug("Error updating status box", exc_info=True)

    # ==================================================================
    # Static helpers
    # ==================================================================

    @staticmethod
    def _fmt_speed(bps: float) -> str:
        if bps < 1024:
            return f"{bps:.0f} B/s"
        if bps < 1_048_576:
            return f"{bps / 1024:.2f} KB/s"
        return f"{bps / 1_048_576:.2f} MB/s"

    @staticmethod
    def _fmt_bytes(size: int) -> str:
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size //= 1024
        return f"{size:.1f} TiB"
