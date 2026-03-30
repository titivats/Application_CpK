from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


class ScrollablePanel(ttk.Frame):
    def __init__(self, master, *, background: str, height: int | None = None) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.canvas = tk.Canvas(
            self,
            background=background,
            highlightthickness=0,
            bd=0,
            relief="flat",
            height=height,
        )
        self.canvas.configure(yscrollincrement=16, xscrollincrement=16)
        self.y_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.x_scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=self.y_scrollbar.set,
            xscrollcommand=self.x_scrollbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.y_scrollbar.grid(row=0, column=1, sticky="ns")
        self.x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.content = ttk.Frame(self, style="Surface.TFrame")
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self._scroll_region_job: str | None = None
        self._resize_job: str | None = None
        self._pending_width: int | None = None

        self.content.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._handle_canvas_resize)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)


    def _sync_scroll_region(self, _event=None) -> None:
        if self._scroll_region_job is None:
            self._scroll_region_job = self.after_idle(self._apply_scroll_region)


    def _apply_scroll_region(self) -> None:
        self._scroll_region_job = None
        if not self.winfo_exists():
            return
        self.canvas.configure(
            scrollregion=(0, 0, self.content.winfo_reqwidth(), self.content.winfo_reqheight())
        )


    def _handle_canvas_resize(self, event) -> None:
        self._pending_width = event.width
        if self._resize_job is None:
            self._resize_job = self.after_idle(self._apply_canvas_width)


    def _apply_canvas_width(self) -> None:
        self._resize_job = None
        if not self.winfo_exists():
            return
        min_width = max(self._pending_width or 0, self.content.winfo_reqwidth())
        self.canvas.itemconfigure(self.window_id, width=min_width)
        self._sync_scroll_region()


    def _bind_mousewheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)


    def _unbind_mousewheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Shift-MouseWheel>")


    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


    def _on_shift_mousewheel(self, event) -> None:
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")


class PreviewImagePanel(ttk.Frame):
    def __init__(self, master, *, background: str) -> None:
        super().__init__(master, style="Surface.TFrame")
        self._background = background
        self.canvas = tk.Canvas(
            self,
            background=background,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.canvas.configure(yscrollincrement=16, xscrollincrement=16)
        self.y_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.x_scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=self.y_scrollbar.set,
            xscrollcommand=self.x_scrollbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.y_scrollbar.grid(row=0, column=1, sticky="ns")
        self.x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._source_image: Image.Image | None = None
        self._photo_image: ImageTk.PhotoImage | None = None
        self._placeholder_text = ""
        self._render_job: str | None = None

        self.canvas.bind("<Configure>", self._schedule_render)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)


    def clear(self) -> None:
        self._source_image = None
        self._photo_image = None
        self._placeholder_text = ""
        self.canvas.delete("all")
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.canvas.winfo_height()))


    def set_placeholder(self, text: str) -> None:
        self._source_image = None
        self._photo_image = None
        self._placeholder_text = text
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._schedule_render()


    def set_image(self, image: Image.Image) -> None:
        self._source_image = image.copy()
        self._photo_image = None
        self._placeholder_text = ""
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._schedule_render()


    def has_content(self) -> bool:
        return self._source_image is not None


    def _schedule_render(self, _event=None) -> None:
        if self._render_job is None:
            self._render_job = self.after_idle(self._render_content)


    def _render_content(self) -> None:
        self._render_job = None
        if not self.winfo_exists():
            return

        self.canvas.delete("all")
        canvas_width = max(self.canvas.winfo_width(), 1)
        padding = 10

        if self._source_image is not None:
            available_width = max(canvas_width - (padding * 2), 320)
            scale = min(1.0, available_width / max(self._source_image.width, 1))
            render_width = max(1, int(round(self._source_image.width * scale)))
            render_height = max(1, int(round(self._source_image.height * scale)))
            if scale < 0.999:
                rendered = self._source_image.resize((render_width, render_height), Image.Resampling.LANCZOS)
            else:
                rendered = self._source_image.copy()

            self._photo_image = ImageTk.PhotoImage(rendered)
            x_offset = max(padding, (canvas_width - render_width) // 2)
            y_offset = padding
            self.canvas.create_image(x_offset, y_offset, anchor="nw", image=self._photo_image)
            self.canvas.configure(
                scrollregion=(0, 0, max(canvas_width, render_width + (padding * 2)), render_height + (padding * 2))
            )
            return

        placeholder = self._placeholder_text or ""
        self.canvas.create_text(
            canvas_width // 2,
            24,
            text=placeholder,
            anchor="n",
            justify="center",
            width=max(canvas_width - 40, 220),
            fill="#5B6670",
            font=("Segoe UI", 10),
        )
        bbox = self.canvas.bbox("all") or (0, 0, canvas_width, 72)
        self.canvas.configure(scrollregion=(0, 0, max(canvas_width, bbox[2] + padding), max(72, bbox[3] + padding)))


    def _bind_mousewheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)


    def _unbind_mousewheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Shift-MouseWheel>")


    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


    def _on_shift_mousewheel(self, event) -> None:
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
