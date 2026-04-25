"""Reusable UI widgets."""

from __future__ import annotations

import tkinter


class Tooltip:
    """Floating tooltip that appears on hover."""

    def __init__(
        self,
        widget: tkinter.Widget,
        text: str,
        font: tuple[str, int] = ("sans-serif", 10),
    ) -> None:
        self._widget = widget
        self._text = text
        self._font = font
        self._window: tkinter.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: tkinter.Event | None = None) -> None:
        if self._window or not self._text:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 5
        self._window = tkinter.Toplevel(self._widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{x}+{y}")
        self._window.attributes("-topmost", True)
        label = tkinter.Label(
            self._window,
            text=self._text,
            justify="left",
            background="#FFFFE0",
            relief="solid",
            borderwidth=1,
            font=self._font,
            wraplength=350,
            padx=5,
            pady=3,
        )
        label.pack(ipadx=1)

    def _hide(self, _event: tkinter.Event | None = None) -> None:
        if self._window:
            self._window.destroy()
        self._window = None
