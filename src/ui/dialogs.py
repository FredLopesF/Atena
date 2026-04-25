"""Modal dialogs: CustomDialog, AddConsoleDialog, ConsoleSelectModal."""

from __future__ import annotations

import math
import tkinter
import tkinter.filedialog
import tkinter.messagebox
import webbrowser
from typing import Callable

import customtkinter as ctk

from src.core.models import Console


# ---------------------------------------------------------------------------
# CustomDialog — generic message dialog with configurable buttons
# ---------------------------------------------------------------------------


class CustomDialog(ctk.CTkToplevel):
    """Modal dialog with a message and a dict of {label: value} buttons."""

    def __init__(
        self,
        parent: ctk.CTk,
        title: str,
        message: str,
        buttons: dict[str, object],
    ) -> None:
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title(title)
        self.result: object = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text=message,
            wraplength=450,
            justify="left",
            font=ctk.CTkFont(size=14),
        ).grid(row=0, column=0, columnspan=len(buttons), padx=20, pady=(15, 25), sticky="ew")

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=1, column=0, columnspan=len(buttons), padx=20, pady=(0, 15), sticky="ew")
        for i in range(len(buttons)):
            btn_frame.grid_columnconfigure(i, weight=1)

        for i, (label, value) in enumerate(buttons.items()):
            ctk.CTkButton(
                btn_frame,
                text=label,
                command=lambda v=value: self._close(v),
                height=35,
                corner_radius=0,
            ).grid(row=0, column=i, padx=5, sticky="ew")

        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        dw, dh = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + pw // 2 - dw // 2}+{py + ph // 2 - dh // 2}")
        self.resizable(False, False)

    def _close(self, value: object) -> None:
        self.result = value
        self.destroy()

    def wait_for_response(self) -> object:
        self.wait_window()
        return self.result


# ---------------------------------------------------------------------------
# AddConsoleDialog — Fase 2 design with archive_org / direct_url selector
# ---------------------------------------------------------------------------


class AddConsoleDialog(ctk.CTkToplevel):
    """Add or edit a console entry.

    Shows dynamic fields depending on the selected source type.
    Uses a callback pattern: on_action(action, console) is called for each
    save/delete operation, but the dialog stays open until explicitly closed.
    """

    _ARCHIVE_LABEL = "Archive.org"
    _DIRECT_LABEL = "URL Direta"

    def __init__(
        self,
        parent: ctk.CTk,
        lang: Callable[[str], str],
        bold_font: ctk.CTkFont,
        consoles: dict[str, Console],
        on_action: Callable[[str, Console], None] | None = None,
        preload: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title(lang("add_console_title"))
        self.resizable(False, False)

        self._lang = lang
        self._bold = bold_font
        self._consoles = consoles
        self._on_action = on_action
        self._action: str | None = None
        self._result: Console | None = None
        self._custom_path_var = tkinter.StringVar()

        dw, dh = 680, 420
        px = parent.winfo_x() + parent.winfo_width() // 2 - dw // 2
        py = parent.winfo_y() + parent.winfo_height() // 2 - dh // 2
        self.geometry(f"{dw}x{dh}+{px}+{py}")
        self.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        frame.grid_columnconfigure(1, weight=1)

        # --- Row 0: Name ---
        ctk.CTkLabel(frame, text=lang("add_console_name_label"), font=bold_font).grid(
            row=0, column=0, padx=10, pady=(10, 5), sticky="w"
        )
        name_row = ctk.CTkFrame(frame, fg_color="transparent")
        name_row.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="ew")
        name_row.grid_columnconfigure(0, weight=1)
        self._name_entry = ctk.CTkEntry(
            name_row,
            font=bold_font,
            height=35,
            corner_radius=0,
            placeholder_text=lang("add_console_new_console_placeholder"),
        )
        self._name_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            name_row,
            text=lang("add_console_select_button"),
            font=bold_font,
            height=35,
            corner_radius=0,
            width=140,
            command=self._pick_existing,
        ).grid(row=0, column=1, padx=(5, 0), sticky="e")

        # --- Row 1: Type ---
        ctk.CTkLabel(frame, text="Tipo:", font=bold_font).grid(
            row=1, column=0, padx=10, pady=5, sticky="w"
        )
        self._type_var = tkinter.StringVar(value=self._ARCHIVE_LABEL)
        self._type_combo = ctk.CTkComboBox(
            frame,
            values=[self._ARCHIVE_LABEL, self._DIRECT_LABEL],
            variable=self._type_var,
            font=bold_font,
            height=35,
            corner_radius=0,
            state="readonly",
            command=self._on_type_change,
        )
        self._type_combo.grid(row=1, column=1, padx=10, pady=5, sticky="w")

        # --- Row 2: Identifier (archive_org) / URL (direct_url) ---
        self._source_label = ctk.CTkLabel(frame, text="Identifier:", font=bold_font)
        self._source_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        src_row = ctk.CTkFrame(frame, fg_color="transparent")
        src_row.grid(row=2, column=1, padx=10, pady=5, sticky="ew")
        src_row.grid_columnconfigure(0, weight=1)
        self._source_entry = ctk.CTkEntry(
            src_row, font=bold_font, height=35, corner_radius=0,
            placeholder_text="ex: nointro.snes",
        )
        self._source_entry.grid(row=0, column=0, sticky="ew")
        self._browse_btn = ctk.CTkButton(
            src_row,
            text="Buscar no Archive.org",
            font=bold_font,
            height=35,
            corner_radius=0,
            width=180,
            command=lambda: webbrowser.open_new_tab(
                "https://archive.org/search?query=no-intro"
            ),
        )
        self._browse_btn.grid(row=0, column=1, padx=(5, 0), sticky="e")

        # --- Row 3: Extensions (optional) ---
        ctk.CTkLabel(frame, text="Extensões (opcional):", font=bold_font).grid(
            row=3, column=0, padx=10, pady=5, sticky="w"
        )
        self._ext_entry = ctk.CTkEntry(
            frame,
            font=bold_font,
            height=35,
            corner_radius=0,
            placeholder_text="ex: .zip,.7z,.chd",
        )
        self._ext_entry.grid(row=3, column=1, padx=10, pady=5, sticky="ew")

        # --- Row 4: Custom path ---
        path_row = ctk.CTkFrame(frame, fg_color="transparent")
        path_row.grid(row=4, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)
        self._path_label = ctk.CTkLabel(
            path_row,
            text=lang("add_console_path_display_default"),
            text_color="gray70",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(slant="italic"),
        )
        self._path_label.grid(row=0, column=0, padx=10, sticky="w")
        self._path_btn = ctk.CTkButton(
            path_row,
            text=lang("add_console_path_select_button"),
            font=bold_font,
            height=35,
            corner_radius=0,
            width=120,
            command=self._toggle_path,
        )
        self._path_btn.grid(row=0, column=1, padx=10, sticky="e")

        # --- Row 5: Authentication (archive.org optional) ---
        self._auth_row = ctk.CTkFrame(frame, fg_color="transparent")
        self._auth_row.grid(row=5, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        self._auth_row.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(self._auth_row, text=lang("add_console_auth_email_label"), font=bold_font).grid(
            row=0, column=0, padx=(0, 10), sticky="w"
        )
        self._email_entry = ctk.CTkEntry(
            self._auth_row, font=bold_font, height=35, corner_radius=0, placeholder_text="example@email.com"
        )
        self._email_entry.grid(row=0, column=1, padx=(0, 20), sticky="ew")

        ctk.CTkLabel(self._auth_row, text=lang("add_console_auth_password_label"), font=bold_font).grid(
            row=0, column=2, padx=(0, 10), sticky="w"
        )
        self._pass_entry = ctk.CTkEntry(
            self._auth_row, font=bold_font, height=35, corner_radius=0, show="*", placeholder_text="***"
        )
        self._pass_entry.grid(row=0, column=3, sticky="ew")

        # --- Row 6: Action buttons ---
        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.grid(row=6, column=0, columnspan=2, padx=10, pady=(15, 10), sticky="ew")
        btn_row.grid_columnconfigure((0, 1, 2), weight=1)
        from src.core.constants import DOWNLOAD_ACTIVE_COLOR, ATTENTION_COLOR

        ctk.CTkButton(
            btn_row,
            text=lang("add_console_update_button"),
            font=bold_font,
            height=35,
            corner_radius=0,
            fg_color=DOWNLOAD_ACTIVE_COLOR,
            command=self._save,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self._delete_btn = ctk.CTkButton(
            btn_row,
            text=lang("add_console_delete_button"),
            font=bold_font,
            height=35,
            corner_radius=0,
            fg_color=ATTENTION_COLOR,
            state="disabled",
            command=self._delete,
        )
        self._delete_btn.grid(row=0, column=1, padx=5, sticky="ew")
        ctk.CTkButton(
            btn_row,
            text=lang("add_console_cancel_button"),
            font=bold_font,
            height=35,
            corner_radius=0,
            command=self.destroy,
        ).grid(row=0, column=2, padx=(5, 0), sticky="ew")

        if preload:
            self._load_console(preload)
        self._name_entry.focus()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def wait_for_result(self) -> tuple[str | None, Console | None]:
        """Legacy blocking API — kept for backward compatibility."""
        self.wait_window()
        return self._action, self._result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_type_change(self, _choice: str) -> None:
        is_archive = self._type_var.get() == self._ARCHIVE_LABEL
        self._source_label.configure(text="Identifier:" if is_archive else "URL:")
        self._source_entry.configure(
            placeholder_text="ex: nointro.snes" if is_archive else "https://..."
        )
        if is_archive:
            self._browse_btn.grid()
            self._auth_row.grid()
        else:
            self._browse_btn.grid_remove()
            self._auth_row.grid_remove()

    def _pick_existing(self) -> None:
        names = sorted(self._consoles.keys())
        if not names:
            return
        picker = ctk.CTkToplevel(self)
        picker.title("Selecionar console")
        picker.transient(self)
        picker.grab_set()
        picker.resizable(False, False)
        frame = ctk.CTkScrollableFrame(picker, fg_color="transparent")
        frame.pack(expand=True, fill="both")
        for name in names:
            ctk.CTkButton(
                frame,
                text=name,
                height=36,
                corner_radius=0,
                command=lambda n=name: (self._load_console(n), picker.destroy()),
            ).pack(fill="x", padx=5, pady=2)

    def _load_console(self, name: str) -> None:
        c = self._consoles.get(name)
        if not c:
            return
        self._name_entry.delete(0, "end")
        self._name_entry.insert(0, name)
        if c.type == "archive_org":
            self._type_var.set(self._ARCHIVE_LABEL)
            self._source_entry.delete(0, "end")
            self._source_entry.insert(0, c.identifier or "")
        else:
            self._type_var.set(self._DIRECT_LABEL)
            self._source_entry.delete(0, "end")
            self._source_entry.insert(0, c.url or "")
        self._on_type_change(self._type_var.get())
        self._ext_entry.delete(0, "end")
        self._ext_entry.insert(0, ",".join(c.extensions) if c.extensions else "")
        if c.path:
            self._custom_path_var.set(c.path)
            self._path_label.configure(text=c.path)
            self._path_btn.configure(text=self._lang("add_console_path_restore_button"))
        self._email_entry.delete(0, "end")
        self._pass_entry.delete(0, "end")
        if c.auth_email:
            self._email_entry.insert(0, c.auth_email)
        if c.auth_password:
            self._pass_entry.insert(0, c.auth_password)
        self._delete_btn.configure(state="normal")

    def _toggle_path(self) -> None:
        lang = self._lang
        if self._path_btn.cget("text") == lang("add_console_path_select_button"):
            path = tkinter.filedialog.askdirectory(
                title=lang("add_console_path_label"), parent=self
            )
            if path:
                self._custom_path_var.set(path)
                self._path_label.configure(text=path)
                self._path_btn.configure(text=lang("add_console_path_restore_button"))
        else:
            self._custom_path_var.set("")
            self._path_label.configure(text=lang("add_console_path_display_default"))
            self._path_btn.configure(text=lang("add_console_path_select_button"))

    def _save(self) -> None:
        name = self._name_entry.get().strip()
        source = self._source_entry.get().strip()
        if not name or not source:
            tkinter.messagebox.showerror(
                self._lang("add_console_input_error_title"),
                self._lang("add_console_input_error_text"),
                parent=self,
            )
            return

        raw_ext = self._ext_entry.get().strip()
        extensions = [e.strip() for e in raw_ext.split(",") if e.strip()] if raw_ext else []
        path = self._custom_path_var.get() or None

        auth_email = self._email_entry.get().strip() or None
        auth_password = self._pass_entry.get() or None

        if self._type_var.get() == self._ARCHIVE_LABEL:
            console = Console(name=name, type="archive_org", identifier=source, extensions=extensions, path=path, auth_email=auth_email, auth_password=auth_password)
        else:
            console = Console(name=name, type="direct_url", url=source, extensions=extensions, path=path)

        action = "update" if name in self._consoles else "add"
        self._action = action
        self._result = console

        # Update local consoles dict so subsequent edits see current state
        self._consoles[name] = console
        self._delete_btn.configure(state="normal")

        if self._on_action:
            self._on_action(action, console)
        else:
            self.destroy()

    def _delete(self) -> None:
        name = self._name_entry.get().strip()
        if not name or name not in self._consoles:
            tkinter.messagebox.showwarning(
                self._lang("add_console_delete_error_title"),
                self._lang("add_console_delete_error_text"),
                parent=self,
            )
            return
        if tkinter.messagebox.askyesno(
            self._lang("add_console_confirm_delete_title"),
            self._lang("add_console_confirm_delete_text", name_to_delete=name),
            icon="warning",
            parent=self,
        ):
            deleted_console = self._consoles[name]
            self._action = "delete"
            self._result = deleted_console

            # Remove from local dict and reset form
            del self._consoles[name]
            self._reset_form()

            if self._on_action:
                self._on_action("delete", deleted_console)
            else:
                self.destroy()

    def _reset_form(self) -> None:
        """Clear all form fields to initial state."""
        self._name_entry.delete(0, "end")
        self._source_entry.delete(0, "end")
        self._ext_entry.delete(0, "end")
        self._email_entry.delete(0, "end")
        self._pass_entry.delete(0, "end")
        self._custom_path_var.set("")
        self._path_label.configure(text=self._lang("add_console_path_display_default"))
        self._path_btn.configure(text=self._lang("add_console_path_select_button"))
        self._type_var.set(self._ARCHIVE_LABEL)
        self._on_type_change(self._ARCHIVE_LABEL)
        self._delete_btn.configure(state="disabled")
        self._name_entry.focus()


# ---------------------------------------------------------------------------
# ConsoleSelectModal — grid of console buttons
# ---------------------------------------------------------------------------


class ConsoleSelectModal(ctk.CTkToplevel):
    """Grid modal for picking a console.

    *on_select(console_name)* is called when the user clicks a button.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        title: str,
        consoles: dict[str, Console],
        on_select: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        names = sorted(consoles.keys())
        if not names:
            ctk.CTkLabel(self, text="No consoles configured.").pack(padx=20, pady=20)
            self.after(2000, self.destroy)
            return

        max_rows = 12
        btn_w, btn_h, pad = 230, 38, 5
        num_cols = math.ceil(len(names) / max_rows)
        num_rows = min(len(names), max_rows)
        dw = btn_w * num_cols + pad * (num_cols + 1)
        dh = btn_h * num_rows + pad * (num_rows + 2) + 20
        px = parent.winfo_x() + parent.winfo_width() // 2 - dw // 2
        py = parent.winfo_y() + parent.winfo_height() // 2 - dh // 2
        self.geometry(f"{dw}x{dh}+{px}+{py}")

        frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        frame.pack(expand=True, fill="both")
        for i in range(num_cols):
            frame.grid_columnconfigure(i, weight=1, minsize=btn_w)

        def _select(name: str) -> None:
            on_select(name)
            self.destroy()

        row = col = 0
        for name in names:
            ctk.CTkButton(
                frame,
                text=name,
                height=btn_h,
                corner_radius=0,
                command=lambda n=name: _select(n),
            ).grid(row=row, column=col, sticky="ew", padx=5, pady=2)
            row += 1
            if row >= max_rows:
                row = 0
                col += 1
