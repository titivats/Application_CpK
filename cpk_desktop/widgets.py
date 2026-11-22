from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
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
        root = self.winfo_toplevel()
        self._wheel_bindings = [(event, root.bind(event, self._on_wheel, add="+"))
                                for event in ("<MouseWheel>", "<Shift-MouseWheel>")]

    def destroy(self) -> None:
        for job in (self._scroll_region_job, self._resize_job):
            if job is not None:
                self.after_cancel(job)
        for event, binding in self._wheel_bindings:
            self.winfo_toplevel().unbind(event, binding)
        super().destroy()

    def _on_wheel(self, event) -> None:
        hovered = self.winfo_containing(event.x_root, event.y_root)
        if hovered is None or not str(hovered).startswith(str(self) + "."):
            return
        scroll = self.canvas.xview_scroll if event.state & 1 else self.canvas.yview_scroll
        scroll(int(-event.delta / 120), "units")

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



class PreviewImagePanel(ttk.Frame):
    def __init__(self, master, *, background: str) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.canvas = tk.Canvas(
            self,
            background=background,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._image_item = self.canvas.create_image(0, 0, anchor="center", state="hidden")
        self._text_item = self.canvas.create_text(
            0, 24, anchor="n", justify="center", fill="#5B6670", font=("Segoe UI", 10)
        )
        self._figure_factory: Callable[[], Figure] | None = None
        self._figure_size = (1.0, 1.0)
        self._photo_image: ImageTk.PhotoImage | None = None
        self._rendered_dpi: float | None = None
        self._render_job: str | None = None

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Map>", self.refresh)

    def destroy(self) -> None:
        self._cancel_render()
        super().destroy()

    def _cancel_render(self) -> None:
        if self._render_job is not None:
            self.after_cancel(self._render_job)
            self._render_job = None

    def set_placeholder(self, text: str) -> None:
        self._cancel_render()
        self._figure_factory = None
        self._rendered_dpi = None
        self.canvas.itemconfigure(self._image_item, image="", state="hidden")
        self._photo_image = None
        self.canvas.itemconfigure(self._text_item, text=text, state="normal")

    def set_figure(self, factory: Callable[[], Figure], figure_size: tuple[float, float]) -> None:
        self._figure_factory = factory
        self._figure_size = figure_size
        self._rendered_dpi = None
        self.refresh()

    def has_content(self) -> bool:
        return self._photo_image is not None

    def refresh(self, _event=None) -> None:
        if self._figure_factory is not None:
            self._cancel_render()
            self._render_job = self.after_idle(self._render_content)

    def _on_resize(self, event) -> None:
        self.canvas.coords(self._image_item, event.width // 2, event.height // 2)
        self.canvas.coords(self._text_item, event.width // 2, 24)
        self.canvas.itemconfigure(self._text_item, width=max(event.width - 40, 1))
        if self._figure_factory is not None:
            if self._photo_image is None:
                self.refresh()
            else:
                # Keep the last complete chart on screen throughout a resize gesture.
                self._cancel_render()
                self._render_job = self.after(90, self._render_content)

    def _render_content(self) -> None:
        self._render_job = None
        if self._figure_factory is None or not self.canvas.winfo_viewable():
            return
        width = self.canvas.winfo_width() - 12
        height = self.canvas.winfo_height() - 12
        dpi = min(width / self._figure_size[0], height / self._figure_size[1])
        if dpi <= 0 or dpi == self._rendered_dpi:
            return

        figure = self._figure_factory()
        try:
            # Support very narrow splitter positions without rasterizing subpixel fonts.
            figure.set_dpi(max(36, dpi))
            canvas = FigureCanvasAgg(figure)
            canvas.draw()
            rendered = Image.frombuffer("RGBA", canvas.get_width_height(), canvas.buffer_rgba())
            if dpi < 36:
                rendered.thumbnail((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(rendered, master=self.canvas)
        finally:
            figure.clear()
        self.canvas.itemconfigure(self._image_item, image=photo, state="normal")
        self.canvas.itemconfigure(self._text_item, state="hidden")
        self._photo_image = photo
        self._rendered_dpi = dpi
