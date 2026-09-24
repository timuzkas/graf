"""tk desktop interface for graf."""

from __future__ import annotations

import math

import json
import logging
import queue
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from otter import ExpressionError, ParsedRelation, __version__ as OTTER_VERSION, parse_relation
from . import __version__ as GRAF_VERSION
from .plotting import (
    Viewport,
    contour_implicit,
    find_axis_crossings,
    find_intersections,
    nice_tick_step,
    sample_explicit_adaptive,
    sample_explicit_inequality,
    sample_inequality,
    sample_parametric,
    sample_polar,
    snap_to_nearest_point,
    refine_intersection,
    stitch_segments,
)
from .theme import Theme, config_path, load_theme, theme_mtime


logger = logging.getLogger(__name__)


def _resource_path(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle_root / name


class IconButton(tk.Canvas):
    """toolbar button drawn with line icons."""

    def __init__(
        self,
        parent: tk.Misc,
        icon: str,
        command: Callable[[], object],
        background: str,
        foreground: str,
        active_background: str,
        active_foreground: str,
    ):
        size = 22 if icon == "info" else 30
        super().__init__(parent, width=size, height=size, bd=0, highlightthickness=0, background=background, cursor="hand2", takefocus=0)
        self.icon = icon
        self.command = command
        self.base_background = background
        self.base_foreground = foreground
        self.active_background = active_background
        self.active_foreground = active_foreground
        self.hovered = False
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    def set_colors(self, background: str, foreground: str, active_background: str, active_foreground: str) -> None:
        self.base_background = background
        self.base_foreground = foreground
        self.active_background = active_background
        self.active_foreground = active_foreground
        self._draw()

    def _enter(self, _event: tk.Event) -> None:
        self.hovered = True
        self._draw()

    def _leave(self, _event: tk.Event) -> None:
        self.hovered = False
        self._draw()

    def _release(self, event: tk.Event) -> None:
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def _draw(self) -> None:
        self.delete("all")
        foreground = self.active_foreground if self.hovered else self.base_foreground
        self.configure(background=self.base_background)
        if self.icon == "info":
            if self.hovered:
                self.create_oval(1, 1, 21, 21, fill=self.active_background, outline="")
            self.create_oval(5, 5, 17, 17, outline=foreground, width=1.5)
            self.create_oval(10, 7.5, 12, 9.5, fill=foreground, outline="")
            self.create_line(11, 11, 11, 15, fill=foreground, width=1.5, capstyle=tk.ROUND)
            return
        if self.hovered:
            self.create_polygon(
                6, 2, 24, 2, 28, 6, 28, 24, 24, 28,
                6, 28, 2, 24, 2, 6,
                fill=self.active_background, outline="", smooth=True,
            )
        if self.icon == "open":
            self.create_line(
                6, 20, 6, 9, 12, 9, 14, 11, 22, 11, 22, 14,
                fill=foreground, width=2, capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            )
            self.create_line(
                6, 14, 10, 14, 12, 12, 24, 12, 21, 21, 7, 21, 6, 14,
                fill=foreground, width=2, capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            )
        elif self.icon == "save_as":
            self.create_line(
                7, 5, 17, 5, 22, 10, 22, 14,
                fill=foreground, width=2, capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            )
            self.create_line(
                7, 5, 7, 23, 14, 23,
                fill=foreground, width=2, capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
            )
            self.create_line(17, 5, 17, 10, 22, 10, fill=foreground, width=2, joinstyle=tk.ROUND)
            self.create_line(14, 22, 21, 15, 24, 18, 17, 25, 13, 26, 14, 22, fill=foreground, width=2, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        else:
            # recenter target, not a refresh action
            self.create_oval(9, 9, 21, 21, outline=foreground, width=2)
            self.create_line(15, 5, 15, 11, fill=foreground, width=2, capstyle=tk.ROUND)
            self.create_line(15, 19, 15, 25, fill=foreground, width=2, capstyle=tk.ROUND)
            self.create_line(5, 15, 11, 15, fill=foreground, width=2, capstyle=tk.ROUND)
            self.create_line(19, 15, 25, 15, fill=foreground, width=2, capstyle=tk.ROUND)
            self.create_oval(14, 14, 16, 16, fill=foreground, outline=foreground)


class MinimalSlider(tk.Canvas):
    """small slider with a filled rail and round thumb."""

    def __init__(
        self,
        parent: tk.Misc,
        variable: tk.DoubleVar,
        lower: float,
        upper: float,
        step: float,
        color: str,
        background: str,
        trough: str,
        command: Callable[[], None],
    ):
        super().__init__(
            parent, height=18, background=background, highlightthickness=0,
            bd=0, relief=tk.FLAT, cursor="hand2", takefocus=1,
        )
        self.variable = variable
        self.lower = lower
        self.upper = upper
        self.step = step
        self.color = color
        self.trough = trough
        self.command = command
        self._trace = variable.trace_add("write", self._variable_changed)
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._set_from_pointer)
        self.bind("<B1-Motion>", self._set_from_pointer)
        self.bind("<Left>", lambda _event: self._nudge(-1))
        self.bind("<Right>", lambda _event: self._nudge(1))

    def get(self) -> float:
        return float(self.variable.get())

    def set(self, value: float) -> None:
        self.variable.set(self._clamp(value))

    def set_range(self, lower: float, upper: float, step: float) -> None:
        self.lower, self.upper, self.step = lower, upper, step
        self.set(self.get())

    def set_colors(self, color: str, background: str, trough: str) -> None:
        self.color, self.trough = color, trough
        self.configure(background=background)
        self._draw()

    def destroy(self) -> None:
        try:
            self.variable.trace_remove("write", self._trace)
        except tk.TclError:
            pass
        super().destroy()

    def _clamp(self, value: float) -> float:
        return min(self.upper, max(self.lower, value))

    def _quantize(self, value: float) -> float:
        if self.step <= 0:
            return self._clamp(value)
        steps = round((value - self.lower) / self.step)
        return self._clamp(self.lower + steps * self.step)

    def _set_from_pointer(self, event: tk.Event) -> None:
        width = max(1, self.winfo_width() - 12)
        fraction = min(1.0, max(0.0, (event.x - 6) / width))
        self.variable.set(self._quantize(self.lower + fraction * (self.upper - self.lower)))
        self.command()

    def _nudge(self, direction: int) -> str:
        self.variable.set(self._quantize(self.get() + direction * self.step))
        self.command()
        return "break"

    def _variable_changed(self, *_args: object) -> None:
        self._draw()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        left, right = 6.0, max(6.0, float(self.winfo_width()) - 6.0)
        middle = max(7.0, float(self.winfo_height()) / 2)
        span = self.upper - self.lower
        fraction = 0.0 if span <= 0 else (self.get() - self.lower) / span
        thumb = left + min(1.0, max(0.0, fraction)) * (right - left)
        self.create_line(left, middle, right, middle, fill=self.trough, width=2)
        self.create_line(left, middle, thumb, middle, fill=self.color, width=2)
        self.create_oval(thumb - 4, middle - 4, thumb + 4, middle + 4, fill=self.color, outline=self.color)


@dataclass
class ExpressionRow:
    frame: tk.Frame
    entry: tk.Entry
    marker: tk.Label
    answer: tk.Label
    warning: tk.Label
    color: str
    enabled: bool = False
    is_assignment: bool = False
    is_function: bool = False
    slider_frame: tk.Frame | None = None
    slider_track_frame: tk.Frame | None = None
    slider: MinimalSlider | None = None
    slider_var: tk.DoubleVar | None = None
    slider_name: str | None = None
    slider_source: str | None = None
    slider_spec_override: tuple[float, float, float] | None = None
    slider_settings_frame: tk.Frame | None = None
    slider_settings_button: tk.Button | None = None
    slider_min_entry: tk.Entry | None = None
    slider_max_entry: tk.Entry | None = None
    slider_step_entry: tk.Entry | None = None
    slider_settings_open: bool = False
    pending_slider_value: float | None = None
    animate_button: tk.Button | None = None
    animation_job: str | None = None
    animation_direction: int = 1
    error_message: str | None = None
    tooltip_job: str | None = None
    tooltip: tk.Toplevel | None = None
    last_geometry: dict | None = None
    last_geometry_source: str | None = None
    last_geometry_view: tuple | None = None


@dataclass(frozen=True)
class RenderRequest:
    missing: list[tuple[tuple, object, dict[str, float], dict[str, Callable], ExpressionRow]]
    width: int
    height: int
    viewport: Viewport
    generation: int
    view_signature: tuple


class GraphApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.theme: Theme = load_theme()
        self._theme_path = config_path()
        self._theme_mtime = theme_mtime(self._theme_path)
        self.project_path: Path | None = None
        self.about_window: tk.Toplevel | None = None
        self.about_logo_image: tk.PhotoImage | None = None
        self.control_tooltip: tk.Toplevel | None = None
        self.control_tooltip_job: str | None = None
        root.title("graf")
        root.geometry("1100x700")
        root.minsize(700, 420)
        root.configure(background=self.theme.background)
        self.viewport = Viewport()
        self.rows: list[ExpressionRow] = []
        self.last_active_slider: ExpressionRow | None = None
        self.redraw_job: str | None = None
        self.redraw_is_live = False
        self.drag_point: tuple[int, int] | None = None
        self.row_drag_item: ExpressionRow | None = None
        self.row_drag_start: tuple[int, int] | None = None
        self.row_dragged = False
        self.row_drag_target: ExpressionRow | None = None
        self._sash_set = False
        self.intersection_points: list[tuple[float, float]] = []
        self.plot_points: list[tuple[float, float]] = []
        self.root_points: list[tuple[float, float]] = []
        self.trace_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self.render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="graf-render")
        self.render_cache: dict[tuple, dict] = {}
        self.pending_render_keys: set[tuple] = set()
        self.render_generation = 0
        self.render_results: queue.Queue[tuple[Future, RenderRequest]] = queue.Queue()
        self.render_future: Future | None = None
        self.queued_render_request: RenderRequest | None = None

        self.panes = tk.PanedWindow(
            root, orient=tk.HORIZONTAL, sashwidth=1, sashrelief=tk.FLAT,
            background=self.theme.divider, bd=0, relief=tk.FLAT, opaqueresize=True,
        )
        self.panes.pack(fill=tk.BOTH, expand=True)
        self.expression_panel = tk.Frame(self.panes, background=self.theme.background, bd=0)
        self.graph_panel = tk.Frame(self.panes, background=self.theme.graph_background, bd=0)
        self.panes.add(self.expression_panel, minsize=190, width=330, stretch="never")
        self.panes.add(self.graph_panel, minsize=280, stretch="always")

        self._build_expression_list()
        self.graph = tk.Canvas(self.graph_panel, background=self.theme.graph_background, highlightthickness=0, bd=0)
        self.graph.pack(fill=tk.BOTH, expand=True)
        self._build_graph_controls()
        self.graph_panel.bind("<Configure>", self._refresh_graph_controls, add="+")
        self.graph.bind("<Configure>", lambda _event: self.schedule_redraw(100))
        self.graph.bind("<ButtonPress-1>", self._start_pan)
        self.graph.bind("<B1-Motion>", self._pan)
        self.graph.bind("<ButtonRelease-1>", self._end_pan)
        self.graph.bind("<MouseWheel>", self._wheel_zoom)
        self.graph.bind("<Button-4>", lambda event: self._zoom_event(event, 1.15))
        self.graph.bind("<Button-5>", lambda event: self._zoom_event(event, 1 / 1.15))
        self.graph.bind("<Motion>", self._hover_point)
        self.graph.bind("<Leave>", self._leave_graph)
        root.bind_all("<Control-0>", self.reset_view)
        root.bind_all("<Control-Shift-T>", self.reload_theme)
        root.bind_all("<Control-s>", self.save_project)
        root.bind_all("<Control-S>", self.save_project_as)
        root.bind_all("<Control-Shift-s>", self.save_project_as)
        root.bind_all("<Control-Shift-S>", self.save_project_as)
        root.bind_all("<Control-o>", self.open_project)
        root.bind_all("<space>", self._space_animation)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self.panes.bind("<Configure>", self._set_initial_sash, add="+")
        root.after(180, self._set_initial_sash)
        self.add_row()
        self.schedule_redraw(0)
        root.after(1200, self._watch_theme)
        root.after(8, self._poll_render_results)

    def _build_expression_list(self) -> None:
        holder = tk.Frame(self.expression_panel, background=self.theme.background)
        holder.pack(fill=tk.BOTH, expand=True, padx=(10, 0), pady=9)
        self.rows_canvas = tk.Canvas(holder, background=self.theme.background, highlightthickness=0, bd=0)
        self.rows_scrollbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self.rows_canvas.yview)
        self.rows_canvas.configure(yscrollcommand=self._set_rows_scrollbar)
        self.rows_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.rows_frame = tk.Frame(self.rows_canvas, background=self.theme.background)
        self.rows_window = self.rows_canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", self._sync_scroll_region)
        self.rows_canvas.bind("<Configure>", self._sync_rows_width)

    def _set_rows_scrollbar(self, first: str, last: str) -> None:
        self.rows_scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.rows_scrollbar.pack_forget()
        elif not self.rows_scrollbar.winfo_manager():
            self.rows_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_graph_controls(self) -> None:
        self.graph_controls = tk.Frame(self.graph_panel, background=self.theme.graph_background, bd=0)
        self.graph_controls.place(relx=1.0, x=-12, y=12, anchor="ne")
        controls = (
            ("info", "About graf", self.show_about),
            ("open", "Open project  Ctrl+O", self.open_project),
            ("save_as", "Save project as  Ctrl+Shift+S", self.save_project_as),
            ("reset", "Recenter  Ctrl+0", self.reset_view),
        )
        self.graph_control_buttons: list[IconButton] = []
        for icon, help_text, command in controls:
            button = IconButton(
                self.graph_controls, icon, command,
                self.theme.graph_background, self.theme.muted,
                self.theme.button_active, self.theme.text,
            )
            button.pack(side=tk.LEFT, padx=(0, 3))
            button.bind("<Enter>", lambda _event, widget=button, text=help_text: self._control_tip_enter(widget, text), add="+")
            button.bind("<Leave>", lambda _event: self._control_tip_leave(), add="+")
            button.bind("<Expose>", lambda _event, current=button: current._draw(), add="+")
            self.graph_control_buttons.append(button)

    def _refresh_graph_controls(self, _event: tk.Event) -> None:
        for button in self.graph_control_buttons:
            button._draw()

    def show_about(self) -> None:
        if self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            self.about_window.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self.about_window = dialog
        dialog.title("About graf")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(background=self.theme.background)

        content = tk.Frame(dialog, background=self.theme.background, padx=30, pady=22)
        content.pack(fill=tk.BOTH, expand=True)
        try:
            logo = tk.PhotoImage(master=dialog, file=str(_resource_path("graf.png"))).subsample(6, 6)
        except tk.TclError:
            logo = None
        if logo is not None:
            self.about_logo_image = logo
            dialog.iconphoto(False, logo)
            tk.Label(content, image=logo, background=self.theme.background, bd=0).pack(pady=(0, 10))
        tk.Label(
            content, text="graf", background=self.theme.background,
            foreground=self.theme.text, font=("TkDefaultFont", 24, "bold"),
        ).pack(pady=(0, 5))
        tk.Label(
            content, text="A small graphing calculator for functions, equations, and data.",
            background=self.theme.background, foreground=self.theme.muted,
            justify=tk.CENTER, wraplength=300, font=("TkDefaultFont", 10),
        ).pack(pady=(0, 18))

        versions = (
            ("graf", GRAF_VERSION),
            ("otter math engine", OTTER_VERSION),
            ("Python", sys.version.split()[0]),
            ("Tk", str(self.root.tk.call("info", "patchlevel"))),
        )
        for name, version in versions:
            tk.Label(
                content, text=f"{name}  {version}", background=self.theme.background,
                foreground=self.theme.text, font=("TkDefaultFont", 9),
            ).pack(pady=2)

        def close() -> None:
            if dialog.winfo_exists():
                dialog.grab_release()
                dialog.destroy()
            self.about_window = None

        close_button = tk.Button(
            content, text="Close", command=close, relief=tk.FLAT,
            background=self.theme.button, foreground=self.theme.text,
            activebackground=self.theme.button_active, activeforeground=self.theme.text,
            padx=14, pady=4, cursor="hand2",
        )
        close_button.pack(pady=(18, 0))
        dialog.bind("<Escape>", lambda _event: close())
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.grab_set()
        close_button.focus_set()

    def _control_tip_enter(self, widget: tk.Widget, message: str) -> None:
        self._control_tip_leave()
        self.control_tooltip_job = self.root.after(350, lambda: self._show_control_tip(widget, message))

    def _control_tip_leave(self) -> None:
        if self.control_tooltip_job is not None:
            self.root.after_cancel(self.control_tooltip_job)
            self.control_tooltip_job = None
        if self.control_tooltip is not None:
            self.control_tooltip.destroy()
            self.control_tooltip = None

    def _show_control_tip(self, widget: tk.Widget, message: str) -> None:
        self.control_tooltip_job = None
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.configure(background=self.theme.divider)
        tk.Label(
            tip, text=message, background=self.theme.button,
            foreground=self.theme.text, padx=7, pady=4,
            font=("TkDefaultFont", 9),
        ).pack(padx=1, pady=1)
        tip.update_idletasks()
        x = widget.winfo_rootx() + widget.winfo_width() - tip.winfo_reqwidth()
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip.geometry(f"+{x}+{y}")
        self.control_tooltip = tip

    def _sync_scroll_region(self, _event: tk.Event) -> None:
        self.rows_canvas.configure(scrollregion=self.rows_canvas.bbox("all"))

    def _sync_rows_width(self, event: tk.Event) -> None:
        self.rows_canvas.itemconfigure(self.rows_window, width=event.width)

    def _set_initial_sash(self, _event: tk.Event | None = None) -> None:
        if self._sash_set:
            return
        width = self.panes.winfo_width()
        if width > 1:
            self.panes.sash_place(0, int(width * 0.30), 0)
            self._sash_set = True

    def add_row(self, text: str = "", focus: bool = True, after: tk.Entry | None = None) -> tk.Entry:
        row = tk.Frame(self.rows_frame, background=self.theme.background)
        row.pack(fill=tk.X, padx=(1, 7), pady=(0, 3))
        header = tk.Frame(row, background=self.theme.background, height=38)
        header.pack(fill=tk.X)
        marker = tk.Label(header, text="●", foreground=self.theme.hidden_dot, background=self.theme.background, font=("TkDefaultFont", 9), cursor="hand2")
        marker.pack(side=tk.LEFT, padx=(5, 8), pady=(8, 0))
        answer = tk.Label(header, text="", foreground=self.theme.muted, background=self.theme.background, font=("TkDefaultFont", 10))
        answer.pack(side=tk.RIGHT, padx=(6, 7))
        warning = tk.Label(header, text="!", foreground=self.theme.error, background=self.theme.background, font=("TkDefaultFont", 10, "bold"), cursor="question_arrow")
        warning.pack(side=tk.RIGHT, padx=(2, 3))
        warning.pack_forget()
        entry = tk.Entry(
            header, relief=tk.FLAT, bd=0,
            background=self.theme.background, foreground=self.theme.text, insertbackground=self.theme.text,
            highlightthickness=0, font=("TkDefaultFont", 12),
        )
        if text:
            entry.insert(0, text)
        entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5), pady=(4, 0))
        entry.bind("<KeyRelease>", self._entry_changed)
        entry.bind("<Return>", self._enter)
        entry.bind("<Alt-Return>", self._alt_enter)
        entry.bind("<Shift-Return>", self._shift_enter)
        entry.bind("<BackSpace>", self._backspace)
        entry.bind("<Control-a>", self._select_all)
        entry.bind("<Control-A>", self._select_all)
        entry.bind("<Control-d>", self._duplicate_row)
        entry.bind("<Control-D>", self._duplicate_row)
        entry.bind("<Up>", lambda event: self._focus_adjacent_row(event, -1))
        entry.bind("<Down>", lambda event: self._focus_adjacent_row(event, 1))
        item = ExpressionRow(row, entry, marker, answer, warning, self.theme.curves[len(self.rows) % len(self.theme.curves)])
        marker.bind("<ButtonPress-1>", lambda event, current=item: self._row_drag_start(event, current))
        marker.bind("<B1-Motion>", self._row_drag_motion)
        marker.bind("<ButtonRelease-1>", self._row_drag_release)
        warning.bind("<Enter>", lambda _event, current=item: self._warning_enter(current))
        warning.bind("<Leave>", lambda _event, current=item: self._warning_leave(current))
        entry.bind("<Enter>", lambda _event, current=item: self._warning_enter(current), add="+")
        entry.bind("<Leave>", lambda _event, current=item: self._warning_leave(current), add="+")
        self.rows.append(item)
        if after is not None:
            current_index = next((i for i, candidate in enumerate(self.rows[:-1]) if candidate.entry is after), len(self.rows) - 2)
            index = current_index + 1
            self.rows.insert(index, self.rows.pop())
            row.pack_forget()
            row.pack(fill=tk.X, padx=(1, 7), pady=(0, 3), before=self.rows[index + 1].frame if index + 1 < len(self.rows) else None)
        if focus:
            entry.focus_set()
        self.schedule_redraw()
        return entry

    def _entry_changed(self, event: tk.Event) -> None:
        entry = event.widget
        if isinstance(entry, tk.Entry):
            entry.configure(highlightthickness=0)
        self._invalidate_render()
        self.schedule_redraw()

    @staticmethod
    def _select_all(event: tk.Event) -> str:
        entry = event.widget
        if isinstance(entry, tk.Entry):
            entry.select_range(0, tk.END)
            entry.icursor(tk.END)
        return "break"

    def _set_row_error(self, item: ExpressionRow, message: str) -> None:
        item.error_message = message.strip() or "Invalid expression"
        item.entry.configure(highlightthickness=1, highlightbackground=self.theme.error, highlightcolor=self.theme.error)
        if not item.warning.winfo_ismapped():
            item.warning.pack(side=tk.RIGHT, padx=(2, 3), before=item.answer)

    def _clear_row_error(self, item: ExpressionRow) -> None:
        item.error_message = None
        if item.tooltip_job is not None:
            self.root.after_cancel(item.tooltip_job)
            item.tooltip_job = None
        if item.tooltip is not None:
            item.tooltip.destroy()
            item.tooltip = None
        item.warning.pack_forget()

    def _warning_enter(self, item: ExpressionRow) -> None:
        if item.error_message is None:
            return
        if item.tooltip_job is not None:
            self.root.after_cancel(item.tooltip_job)
        item.tooltip_job = self.root.after(260, lambda current=item: self._show_error_tooltip(current))

    def _warning_leave(self, item: ExpressionRow) -> None:
        if item.tooltip_job is not None:
            self.root.after_cancel(item.tooltip_job)
            item.tooltip_job = None
        if item.tooltip is not None:
            item.tooltip.destroy()
            item.tooltip = None

    def _show_error_tooltip(self, item: ExpressionRow) -> None:
        item.tooltip_job = None
        if item.error_message is None or not item.warning.winfo_ismapped():
            return
        tooltip = tk.Toplevel(self.root)
        tooltip.overrideredirect(True)
        tooltip.configure(background=self.theme.divider)
        label = tk.Label(
            tooltip, text=item.error_message, justify=tk.LEFT,
            background=self.theme.button, foreground=self.theme.text,
            padx=7, pady=4, font=("TkDefaultFont", 9),
        )
        label.pack(padx=1, pady=1)
        x = item.warning.winfo_rootx()
        y = item.warning.winfo_rooty() + item.warning.winfo_height() + 4
        tooltip.geometry(f"+{x}+{y}")
        item.tooltip = tooltip

    def _enter(self, _event: tk.Event) -> str:
        self.schedule_redraw(0)
        return "break"

    def _alt_enter(self, event: tk.Event) -> str:
        item = next((candidate for candidate in self.rows if candidate.entry is event.widget), None)
        if item is not None:
            self._toggle_row(item.frame)
        return "break"

    def _shift_enter(self, event: tk.Event) -> str:
        self.add_row(focus=True, after=event.widget)
        return "break"

    def _duplicate_row(self, event: tk.Event) -> str:
        item = next((candidate for candidate in self.rows if candidate.entry is event.widget), None)
        if item is None:
            return "break"
        entry = self.add_row(item.entry.get(), focus=True, after=item.entry)
        duplicate = next(candidate for candidate in self.rows if candidate.entry is entry)
        duplicate.enabled = item.enabled
        duplicate.marker.configure(foreground=duplicate.color if duplicate.enabled else self.theme.hidden_dot)
        self._recolor_rows()
        self._invalidate_render()
        self.schedule_redraw(0)
        return "break"

    def _focus_adjacent_row(self, event: tk.Event, offset: int) -> str:
        index = next((index for index, item in enumerate(self.rows) if item.entry is event.widget), -1)
        target = index + offset
        if index < 0 or not 0 <= target < len(self.rows):
            return "break"
        entry = self.rows[target].entry
        entry.focus_set()
        entry.icursor(min(event.widget.index(tk.INSERT), len(entry.get())))
        return "break"

    def _toggle_row(self, row_frame: tk.Frame) -> None:
        item = next((candidate for candidate in self.rows if candidate.frame is row_frame), None)
        if item is None or item.is_assignment or item.is_function:
            return
        item.enabled = not item.enabled
        item.marker.configure(foreground=item.color if item.enabled else self.theme.hidden_dot)
        self._invalidate_render()
        self.schedule_redraw(0)

    def _row_drag_start(self, event: tk.Event, item: ExpressionRow) -> None:
        self.row_drag_item = item
        self.row_drag_start = (event.x_root, event.y_root)
        self.row_dragged = False
        self.row_drag_target = None

    def _row_drag_motion(self, event: tk.Event) -> None:
        item = self.row_drag_item
        if item is None or self.row_drag_start is None:
            return
        if not self.row_dragged:
            dx = event.x_root - self.row_drag_start[0]
            dy = event.y_root - self.row_drag_start[1]
            if dx * dx + dy * dy < 25:
                return
            self.row_dragged = True
            item.marker.configure(text="⠿", cursor="fleur")
        index = sum(
            1 for candidate in self.rows
            if candidate is not item and event.y_root > candidate.frame.winfo_rooty() + candidate.frame.winfo_height() / 2
        )
        current_index = self.rows.index(item)
        if current_index == index:
            return
        self.rows.pop(current_index)
        self.rows.insert(index, item)
        self._arrange_rows()
        self.row_drag_target = item

    def _row_drag_release(self, _event: tk.Event) -> None:
        item = self.row_drag_item
        if item is None:
            return
        if self.row_dragged:
            self._recolor_rows()
            self._invalidate_render()
            self.schedule_redraw(0)
        else:
            self._toggle_row(item.frame)
        item.marker.configure(text="●", cursor="hand2" if not item.is_assignment and not item.is_function else "")
        self.row_drag_item = None
        self.row_drag_start = None
        self.row_dragged = False
        self.row_drag_target = None

    def _arrange_rows(self) -> None:
        for index, item in enumerate(self.rows):
            following = self.rows[index + 1].frame if index + 1 < len(self.rows) else None
            if following is not None:
                item.frame.pack_configure(before=following)
            elif index:
                item.frame.pack_configure(after=self.rows[index - 1].frame)

    def _recolor_rows(self) -> None:
        for index, item in enumerate(self.rows):
            item.color = self.theme.curves[index % len(self.theme.curves)]
            item.marker.configure(foreground=item.color if item.enabled else self.theme.hidden_dot)
            if item.animate_button is not None:
                running = item.animation_job is not None
                item.animate_button.configure(activeforeground=item.color, foreground=item.color if running else self.theme.muted)
            if item.slider is not None:
                item.slider.set_colors(item.color, self.theme.background, self.theme.trough)

    def _backspace(self, event: tk.Event) -> str | None:
        entry = event.widget
        if not isinstance(entry, tk.Entry) or entry.get() or len(self.rows) <= 1:
            return None
        for index, candidate in enumerate(self.rows):
            if candidate.entry is entry:
                removed = self.rows.pop(index)
                self._clear_row_error(removed)
                removed.frame.destroy()
                self.rows[max(0, index - 1)].entry.focus_set()
                self._invalidate_render()
                self.schedule_redraw()
                return "break"
        return None

    def schedule_redraw(self, delay: int = 120) -> None:
        if self.redraw_job is not None:
            self.root.after_cancel(self.redraw_job)
        self.redraw_is_live = False
        self.redraw_job = self.root.after(delay, self.redraw)

    def schedule_live_redraw(self) -> None:
        """coalesce interaction updates to one redraw per frame."""
        if self.redraw_job is not None and self.redraw_is_live:
            return
        if self.redraw_job is not None:
            self.root.after_cancel(self.redraw_job)
        self.redraw_is_live = True
        self.redraw_job = self.root.after(16, self.redraw)

    def _invalidate_render(self) -> None:
        self.render_generation += 1

    def redraw(self) -> None:
        self.redraw_job = None
        self.redraw_is_live = False
        canvas = self.graph
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 2 or height < 2:
            return
        view_signature = self._viewport_signature(width, height, self.viewport)
        canvas.delete("all")
        self.intersection_points.clear()
        self.plot_points.clear()
        self.root_points.clear()
        self.trace_segments.clear()
        self._draw_grid(width, height)
        environment: dict[str, object] = {}
        functions: dict[str, Callable] = {}
        answer_history: list[float] = []
        previous_answer: float | None = None
        rendered_curves: list[list[tuple[tuple[float, float], tuple[float, float]]]] = []
        curve_sources: list[tuple[ParsedRelation, dict, dict]] = []
        missing: list[tuple[tuple, object, dict[str, float], dict[str, Callable], ExpressionRow]] = []
        for item in self.rows:
            item.answer.configure(text="")
            self._clear_row_error(item)
            source = item.entry.get().strip()
            if not source:
                self._remove_slider(item)
                item.slider_spec_override = None
                item.slider_settings_open = False
                item.is_assignment = False
                item.is_function = False
                previous_answer = None
                continue
            available = set(environment)
            if previous_answer is not None:
                available.add("ans")
            try:
                relation = parse_relation(source, available, set(functions))
                item.entry.configure(highlightthickness=0)
                item.is_assignment = relation.kind == "assignment"
                item.is_function = relation.kind == "function"
                item.marker.configure(cursor="" if item.is_assignment or item.is_function else "hand2")
            except ExpressionError as error:
                self._set_row_error(item, str(error))
                self._remove_slider(item)
                item.is_assignment = False
                item.is_function = False
                previous_answer = None
                continue

            evaluation_variables = dict(environment)
            if previous_answer is not None:
                evaluation_variables["ans"] = previous_answer
            evaluation_variables["ans_history"] = list(answer_history)

            if relation.kind == "function":
                name = relation.variable_name
                if name is None or name in functions or name in environment:
                    self._set_row_error(item, "That name is already defined")
                    previous_answer = None
                    continue
                outer_variables = dict(evaluation_variables)
                parameters = relation.function_args

                def defined_function(*args: float, _relation=relation, _parameters=parameters, _outer=outer_variables, _name=name) -> float:
                    if len(args) != len(_parameters):
                        raise ValueError(f"{_name} expects {len(_parameters)} argument(s)")
                    local = dict(_outer)
                    local.update(zip(_parameters, args))
                    coordinate_x = args[_parameters.index("x")] if "x" in _parameters else 0.0
                    coordinate_y = args[_parameters.index("y")] if "y" in _parameters else 0.0
                    value = _relation._compiled(coordinate_x, coordinate_y, local, functions)
                    if isinstance(value, complex) or not math.isfinite(float(value)):
                        raise ValueError("Function result is not finite")
                    return float(value)

                defined_function.__graf_source__ = source  # type: ignore[attr-defined]
                functions[name] = defined_function
                item.answer.configure(text="ƒ")
                self._remove_slider(item)
                previous_answer = None
                continue

            if relation.kind == "assignment":
                name = relation.variable_name
                if name is None or name in environment:
                    self._set_row_error(item, "That variable is already defined")
                    self._remove_slider(item)
                    previous_answer = None
                    continue
                default_value = relation.constant_value()
                if default_value is not None:
                    if item.slider_source is not None and item.slider_source != source:
                        item.slider_spec_override = None
                    spec = item.slider_spec_override or relation.slider
                    self._sync_slider(item, name, source, default_value, spec)
                    value: object = float(item.slider.get()) if item.slider is not None else default_value
                else:
                    self._remove_slider(item)
                    value = relation.assigned_value(evaluation_variables, functions)
                if value is None:
                    self._set_row_error(item, "Could not evaluate this value")
                    previous_answer = None
                    continue
                if not isinstance(value, float):
                    environment[name] = value
                    item.answer.configure(text=f"= {self._format_value(value)}")
                    previous_answer = None
                    continue
                if not math.isfinite(value):
                    self._set_row_error(item, "Could not evaluate this value")
                    previous_answer = None
                    continue
                environment[name] = value
                item.answer.configure(text=f"= {value:.10g}")
                previous_answer = value
                answer_history.insert(0, value)
                del answer_history[100:]
                continue

            self._remove_slider(item)
            scalar = relation.scalar_value(evaluation_variables, functions)
            if scalar is None and relation.is_scalar_expression():
                self._set_row_error(item, "Could not evaluate this expression")
            if relation.kind in ("list", "polygon"):
                try:
                    value = relation.evaluate_value(evaluation_variables, functions)
                    points = relation.point_values(evaluation_variables, functions)
                except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError, IndexError) as error:
                    item.answer.configure(text="")
                    self._set_row_error(item, str(error))
                    previous_answer = None
                    continue
                item.answer.configure(text="" if relation.kind == "polygon" else f"= {self._format_value(value)}")
                if points and item.enabled:
                    screen_points = [self.viewport.world_to_screen(px, py, width, height) for px, py in points]
                    geometry: dict = {"points": screen_points, "segments": []}
                    if relation.kind == "polygon" and len(screen_points) >= 2:
                        geometry["paths"] = [screen_points]
                        if len(screen_points) >= 3:
                            geometry["polygons"] = [screen_points]
                    self._draw_geometry(item, geometry, 0.30 if relation.kind == "polygon" else 0.16)
                previous_answer = None
                continue
            if relation.kind == "point":
                try:
                    value = relation.evaluate_point(evaluation_variables, functions)
                    item.answer.configure(text=f"= {self._format_value(value)}")
                    if item.enabled:
                        px, py = self.viewport.world_to_screen(value[0], value[1], width, height)
                        geometry = {"points": [(px, py)], "segments": []}
                        self._draw_geometry(item, geometry)
                except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError) as error:
                    item.answer.configure(text="")
                    self._set_row_error(item, str(error))
                previous_answer = None
                continue
            if scalar is not None:
                item.answer.configure(text=f"= {scalar:.10g}")
                answer_history.insert(0, scalar)
                del answer_history[100:]
            previous_answer = scalar
            if not item.enabled:
                continue
            cache_key = self._cache_key(source, relation.kind, evaluation_variables, functions, width, height, self.viewport)
            geometry = self.render_cache.get(cache_key)
            if geometry is None:
                if item.last_geometry is not None and item.last_geometry_source == source and item.last_geometry_view is not None:
                    fallback = item.last_geometry if item.last_geometry_view == view_signature else self._remap_geometry(item.last_geometry, item.last_geometry_view, view_signature)
                    self._draw_geometry(item, fallback)
                    rendered_curves.append(fallback.get("segments", []))
                    curve_sources.append((relation, dict(evaluation_variables), dict(functions)))
                    self.trace_segments.extend(fallback.get("segments", []))
                if cache_key not in self.pending_render_keys:
                    missing.append((cache_key, relation, dict(evaluation_variables), dict(functions), item))
                continue
            item.last_geometry = geometry
            item.last_geometry_source = source
            item.last_geometry_view = view_signature
            self._draw_geometry(item, geometry)
            rendered_curves.append(geometry.get("segments", []))
            curve_sources.append((relation, dict(evaluation_variables), dict(functions)))
            self.trace_segments.extend(geometry.get("segments", []))

        axis_y = self.viewport.world_to_screen(0, 0, width, height)[1]
        self.root_points = find_axis_crossings(rendered_curves, axis_y, width)
        for px, py in self.root_points:
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=self.theme.graph_background, outline=self.theme.text, width=1, tags=("scene", "root"))
        self.intersection_points = find_intersections(
            rendered_curves,
            refine=lambda first, second, point: refine_intersection(
                point, curve_sources[first], curve_sources[second], self.viewport, width, height,
            ),
        )
        for index, (px, py) in enumerate(self.intersection_points):
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#ffffff", outline="#555555", width=1, tags=("scene", "intersection", f"intersection-{index}"))
        if missing:
            viewport = Viewport(self.viewport.center_x, self.viewport.center_y, self.viewport.scale)
            self._queue_render(RenderRequest(missing, width, height, viewport, self.render_generation, view_signature))

    @staticmethod
    def _viewport_signature(width: int, height: int, viewport: Viewport) -> tuple:
        return (width, height, round(viewport.center_x, 8), round(viewport.center_y, 8), round(viewport.scale, 8))

    @staticmethod
    def _remap_geometry(geometry: dict, old_view: tuple, new_view: tuple) -> dict:
        """move cached screen geometry between viewports."""
        old_width, old_height, old_x, old_y, old_scale = old_view
        new_width, new_height, new_x, new_y, new_scale = new_view

        def point(value: tuple[float, float]) -> tuple[float, float]:
            px, py = value
            world_x = old_x + (px - old_width / 2) / old_scale
            world_y = old_y - (py - old_height / 2) / old_scale
            return (
                new_width / 2 + (world_x - new_x) * new_scale,
                new_height / 2 - (world_y - new_y) * new_scale,
            )

        remapped: dict = {}
        if "points" in geometry:
            remapped["points"] = [point(value) for value in geometry["points"]]
        if "paths" in geometry:
            remapped["paths"] = [[point(value) for value in path] for path in geometry["paths"]]
        if "polygons" in geometry:
            remapped["polygons"] = [[point(value) for value in polygon] for polygon in geometry["polygons"]]
        if "segments" in geometry:
            remapped["segments"] = [(point(first), point(second)) for first, second in geometry["segments"]]
        if "rectangles" in geometry:
            rectangles = []
            for left, top, right, bottom in geometry["rectangles"]:
                first = point((left, top))
                second = point((right, bottom))
                rectangles.append((min(first[0], second[0]), min(first[1], second[1]), max(first[0], second[0]), max(first[1], second[1])))
            remapped["rectangles"] = rectangles
        return remapped

    @staticmethod
    def _cache_key(source: str, kind: str, variables: dict[str, float], functions: dict[str, Callable], width: int, height: int, viewport: Viewport) -> tuple:
        function_signature = tuple(sorted((name, getattr(function, "__graf_source__", name)) for name, function in functions.items()))
        history_signature = tuple(round(value, 8) for value in variables.get("ans_history", ()))
        values_signature = tuple(sorted(
            (name, round(value, 8) if isinstance(value, float) else repr(value))
            for name, value in variables.items() if name != "ans_history"
        ))
        return (source, kind, values_signature, history_signature, function_signature, width, height, round(viewport.center_x, 8), round(viewport.center_y, 8), round(viewport.scale, 8))

    @staticmethod
    def _render_missing(missing: list[tuple[tuple, object, dict[str, float], dict[str, Callable], ExpressionRow]], width: int, height: int, viewport: Viewport) -> list[tuple[tuple, ExpressionRow, str, dict]]:
        results: list[tuple[tuple, ExpressionRow, str, dict]] = []
        for cache_key, relation, variables, functions, _item in missing:
            if relation.kind == "explicit":
                paths = sample_explicit_adaptive(relation, viewport, width, height, variables, functions)
                geometry = {"paths": paths, "segments": [segment for path in paths for segment in zip(path, path[1:])]}
            elif relation.kind == "polar":
                paths = sample_polar(relation, viewport, width, height, variables, functions)
                geometry = {"paths": paths, "segments": [segment for path in paths for segment in zip(path, path[1:])]}
            elif relation.kind == "parametric":
                paths = sample_parametric(relation, viewport, width, height, variables, functions)
                geometry = {"paths": paths, "segments": [segment for path in paths for segment in zip(path, path[1:])]}
            elif relation.kind == "inequality":
                explicit_fill = sample_explicit_inequality(relation, viewport, width, height, variables, functions)
                if explicit_fill is not None:
                    paths, polygons = explicit_fill
                    segments = [segment for path in paths for segment in zip(path, path[1:])]
                    geometry = {"polygons": polygons, "paths": paths, "segments": segments}
                else:
                    segments = contour_implicit(relation, viewport, width, height, variables=variables, functions=functions)
                    geometry = {"rectangles": sample_inequality(relation, viewport, width, height, variables, functions=functions), "paths": stitch_segments(segments), "segments": segments}
            else:
                segments = contour_implicit(relation, viewport, width, height, variables=variables, functions=functions)
                geometry = {"paths": stitch_segments(segments), "segments": segments}
            results.append((cache_key, _item, relation.source, geometry))
        return results

    def _queue_render(self, request: RenderRequest) -> None:
        if self.render_future is not None:
            self.queued_render_request = request
            return
        self._start_render(request)

    def _start_render(self, request: RenderRequest) -> None:
        missing = [entry for entry in request.missing if entry[0] not in self.render_cache]
        if not missing:
            return
        request = RenderRequest(missing, request.width, request.height, request.viewport, request.generation, request.view_signature)
        self.pending_render_keys.update(entry[0] for entry in missing)
        future = self.render_executor.submit(self._render_missing, missing, request.width, request.height, request.viewport)
        self.render_future = future
        future.add_done_callback(lambda completed, current=request: self.render_results.put((completed, current)))

    def _poll_render_results(self) -> None:
        try:
            while True:
                future, request = self.render_results.get_nowait()
                self._render_finished(future, request)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(8, self._poll_render_results)

    def _render_finished(self, future: Future, request: RenderRequest) -> None:
        try:
            results = future.result()
        except Exception:
            logger.exception("Render failed for %d row(s)", len(request.missing))
            results = []
        for cache_key, item, source, geometry in results:
            self.pending_render_keys.discard(cache_key)
            self.render_cache[cache_key] = geometry
            item.last_geometry = geometry
            item.last_geometry_source = source
            item.last_geometry_view = request.view_signature
            while len(self.render_cache) > 128:
                self.render_cache.pop(next(iter(self.render_cache)))
        if not results:
            for cache_key, _relation, _variables, _functions, _item in request.missing:
                self.pending_render_keys.discard(cache_key)
        if self.render_future is future:
            self.render_future = None
        queued = self.queued_render_request
        self.queued_render_request = None
        if queued is not None:
            self._start_render(queued)
        if results and request.generation == self.render_generation:
            self.schedule_live_redraw()

    def _draw_geometry(self, item: ExpressionRow, geometry: dict, fill_amount: float = 0.16) -> None:
        fill_color = self._blend_color(item.color, self.theme.graph_background, fill_amount)
        for px, py in geometry.get("points", ()):
            # only point rows land here; hover reads these with intersections
            self.plot_points.append((px, py))
            self.graph.create_oval(px - 4, py - 4, px + 4, py + 4, fill=item.color, outline="", tags="scene")
        for polygon in geometry.get("polygons", ()):
            coords = [coordinate for point in polygon for coordinate in point]
            if len(coords) >= 6:
                self.graph.create_polygon(*coords, fill=fill_color, outline="", tags="scene")
        for left, top, right, bottom in geometry.get("rectangles", ()):
            self.graph.create_rectangle(left, top, right, bottom, fill=fill_color, outline="", tags="scene")
        for path in geometry.get("paths", ()):
            coords = [coordinate for point in path for coordinate in point]
            if len(coords) >= 4:
                self.graph.create_line(*coords, fill=item.color, width=2, smooth=False, tags="scene")

    @staticmethod
    def _blend_color(foreground: str, background: str, amount: float) -> str:
        def rgb(value: str) -> tuple[int, int, int]:
            value = value.lstrip("#")
            if len(value) == 3:
                value = "".join(channel * 2 for channel in value)
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]

        front, back = rgb(foreground), rgb(background)
        mixed = tuple(round(back[index] + (front[index] - back[index]) * amount) for index in range(3))
        return "#%02x%02x%02x" % mixed

    def _sync_slider(self, item: ExpressionRow, name: str, source: str, value: float, spec: tuple[float, float, float] | None = None) -> None:
        if spec is not None:
            lower, upper, resolution = spec
        else:
            span = max(10.0, abs(value) * 0.5)
            lower, upper, resolution = min(-10.0, value - span), max(10.0, value + span), None
        effective_step = resolution or (upper - lower) / 200
        if item.slider is None or item.slider_name != name:
            self._remove_slider(item)
            initial_value = item.pending_slider_value if item.pending_slider_value is not None else value
            item.pending_slider_value = None
            item.slider_var = tk.DoubleVar(master=self.root, value=min(upper, max(lower, initial_value)))
            item.slider_frame = tk.Frame(item.frame, background=self.theme.background, bd=0)
            item.slider_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=(25, 8), pady=(0, 4))
            item.slider_track_frame = tk.Frame(item.slider_frame, background=self.theme.background, bd=0)
            item.slider_track_frame.pack(side=tk.TOP, fill=tk.X)
            item.animate_button = tk.Button(
                item.slider_track_frame, text="▶", command=lambda current=item: self._toggle_animation(current),
                relief=tk.FLAT, bd=0, padx=0, pady=0, width=2,
                background=self.theme.background, foreground=self.theme.muted,
                activebackground=self.theme.background, activeforeground=item.color,
                highlightthickness=0, cursor="hand2", font=("TkDefaultFont", 8),
                takefocus=False,
            )
            item.animate_button.pack(side=tk.LEFT, padx=(0, 4))
            item.slider_settings_button = tk.Button(
                item.slider_track_frame, text=">", command=lambda current=item: self._toggle_slider_settings(current),
                relief=tk.FLAT, bd=0, padx=1, pady=0, width=2,
                background=self.theme.background, foreground=self.theme.muted,
                activebackground=self.theme.background, activeforeground=self.theme.text,
                highlightthickness=0, cursor="hand2", font=("TkDefaultFont", 8),
                takefocus=False,
            )
            item.slider_settings_button.pack(side=tk.RIGHT, padx=(4, 0))
            item.slider = MinimalSlider(
                item.slider_track_frame, item.slider_var, lower, upper,
                effective_step,
                item.color, self.theme.background, self.theme.trough,
                lambda current=item: self._slider_changed(current),
            )
            item.slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
            item.slider_settings_frame = self._build_slider_settings(item, lower, upper, effective_step)
            item.slider_name = name
            item.slider_source = source
            if item.slider_settings_open and item.slider_settings_frame is not None:
                item.slider_settings_frame.pack(side=tk.TOP, fill=tk.X, padx=(26, 22), pady=(2, 1))
                item.slider_settings_button.configure(text="v")
        else:
            source_changed = item.slider_source != source
            range_changed = (item.slider.lower, item.slider.upper, item.slider.step) != (lower, upper, effective_step)
            if range_changed:
                item.slider.set_range(lower, upper, effective_step)
            if source_changed:
                item.slider.set(value)
            if source_changed:
                item.slider_source = source
                self._set_slider_setting_values(item, lower, upper, effective_step)

    def _build_slider_settings(self, item: ExpressionRow, lower: float, upper: float, step: float) -> tk.Frame:
        settings = tk.Frame(item.slider_frame, background=self.theme.background, bd=0)
        fields: list[tuple[str, str]] = [("min", f"{lower:g}"), ("max", f"{upper:g}"), ("step", f"{step:g}")]
        entries: list[tk.Entry] = []
        for label_text, initial in fields:
            tk.Label(settings, text=label_text, background=self.theme.background, foreground=self.theme.muted, font=("TkDefaultFont", 8)).pack(side=tk.LEFT, padx=(0, 3))
            entry = tk.Entry(
                settings, width=5, relief=tk.FLAT, bd=0,
                background=self.theme.button, foreground=self.theme.text,
                insertbackground=self.theme.text, highlightthickness=0,
                font=("TkDefaultFont", 9), justify=tk.CENTER,
            )
            entry.insert(0, initial)
            entry.pack(side=tk.LEFT, padx=(0, 8), ipady=2)
            entry.bind("<Return>", lambda event, current=item: self._commit_slider_settings(current, event))
            entry.bind("<FocusOut>", lambda event, current=item: self._commit_slider_settings(current, event))
            entries.append(entry)
        item.slider_min_entry, item.slider_max_entry, item.slider_step_entry = entries
        return settings

    @staticmethod
    def _set_slider_setting_values(item: ExpressionRow, lower: float, upper: float, step: float) -> None:
        for entry, value in zip((item.slider_min_entry, item.slider_max_entry, item.slider_step_entry), (lower, upper, step)):
            if entry is not None:
                entry.delete(0, tk.END)
                entry.insert(0, f"{value:g}")

    def _toggle_slider_settings(self, item: ExpressionRow) -> None:
        if item.slider_settings_frame is None or item.slider_settings_button is None:
            return
        item.slider_settings_open = not item.slider_settings_open
        if item.slider_settings_open:
            item.slider_settings_frame.pack(side=tk.TOP, fill=tk.X, padx=(26, 22), pady=(2, 1))
            item.slider_settings_button.configure(text="v")
            if item.slider is not None:
                self._set_slider_setting_values(item, item.slider.lower, item.slider.upper, item.slider.step)
        else:
            item.slider_settings_frame.pack_forget()
            item.slider_settings_button.configure(text=">")

    def _commit_slider_settings(self, item: ExpressionRow, event: tk.Event | None = None) -> str | None:
        is_return = event is not None and getattr(event, "keysym", "") == "Return"
        entries = (item.slider_min_entry, item.slider_max_entry, item.slider_step_entry)
        if any(entry is None for entry in entries):
            return "break" if is_return else None
        try:
            lower, upper, step = (float(entry.get()) for entry in entries if entry is not None)
            if not all(math.isfinite(value) for value in (lower, upper, step)) or lower >= upper or step <= 0:
                raise ValueError
        except ValueError:
            for entry in entries:
                if entry is not None:
                    entry.configure(highlightthickness=1, highlightbackground=self.theme.error, highlightcolor=self.theme.error)
            self._set_row_error(item, "Slider settings need finite values, min < max, and step > 0")
            return "break" if is_return else None
        for entry in entries:
            if entry is not None:
                entry.configure(highlightthickness=0)
        self._clear_row_error(item)
        item.slider_spec_override = (lower, upper, step)
        self._invalidate_render()
        self.schedule_redraw(0)
        return "break" if is_return else None

    def _toggle_animation(self, item: ExpressionRow) -> None:
        if item.slider is None or item.slider_var is None:
            return
        self.last_active_slider = item
        if item.animation_job is not None:
            self.root.after_cancel(item.animation_job)
            item.animation_job = None
            if item.animate_button is not None:
                item.animate_button.configure(text="▶", foreground=self.theme.muted)
            return
        item.animation_direction = 1
        if item.animate_button is not None:
            item.animate_button.configure(text="Ⅱ", foreground=item.color)
        self._animate_step(item)

    def _animate_step(self, item: ExpressionRow) -> None:
        if item.slider is None or item.slider_var is None or item.animate_button is None or item.animate_button.cget("text") != "Ⅱ":
            item.animation_job = None
            return
        lower = item.slider.lower
        upper = item.slider.upper
        resolution = item.slider.step
        value = float(item.slider_var.get()) + item.animation_direction * max(resolution, (upper - lower) / 160)
        if value >= upper:
            value, item.animation_direction = upper, -1
        elif value <= lower:
            value, item.animation_direction = lower, 1
        item.slider_var.set(value)
        self._slider_changed(item)
        item.animation_job = self.root.after(33, lambda: self._animate_step(item))

    def _slider_changed(self, item: ExpressionRow | None = None) -> None:
        if item is not None and item.slider is not None:
            self.last_active_slider = item
        self._invalidate_render()
        self.schedule_live_redraw()

    def _space_animation(self, event: tk.Event) -> str | None:
        # space keeps its normal job inside entries
        if event.widget.winfo_class() in ("Entry", "Text", "TEntry", "Spinbox", "TSpinbox"):
            return None
        item = self.last_active_slider
        if item is None or item not in self.rows or item.slider is None:
            return None
        self._toggle_animation(item)
        return "break"

    @staticmethod
    def _remove_slider(item: ExpressionRow) -> None:
        if item.animation_job is not None:
            try:
                item.frame.after_cancel(item.animation_job)
            except tk.TclError:
                pass
            item.animation_job = None
        if item.slider is not None:
            item.slider.destroy()
        if item.slider_frame is not None:
            item.slider_frame.destroy()
        elif item.animate_button is not None:
            item.animate_button.destroy()
        item.slider_frame = None
        item.slider_track_frame = None
        item.slider_settings_frame = None
        item.slider_settings_button = None
        item.slider_min_entry = None
        item.slider_max_entry = None
        item.slider_step_entry = None
        item.slider = None
        item.slider_var = None
        item.slider_name = None
        item.slider_source = None
        item.animate_button = None

    @staticmethod
    def _format_value(value: object) -> str:
        if isinstance(value, float):
            return f"{value:.10g}"
        if isinstance(value, tuple):
            return "(" + ", ".join(GraphApp._format_value(part) for part in value) + ")"
        if isinstance(value, list):
            return "[" + ", ".join(GraphApp._format_value(part) for part in value) + "]"
        return str(value)

    def _hover_point(self, event: tk.Event) -> None:
        self.graph.delete("hover")
        if event.state & 0x0001:  # Shift disables point and curve snapping.
            nearest = (float(event.x), float(event.y))
        else:
            nearest = snap_to_nearest_point(
                (float(event.x), float(event.y)),
                self.intersection_points + self.plot_points + self.root_points,
            )
            if nearest is None:
                nearest_distance = float("inf")
                for first, second in self.trace_segments:
                    dx, dy = second[0] - first[0], second[1] - first[1]
                    length2 = dx * dx + dy * dy
                    if length2 <= 1e-12:
                        continue
                    fraction = min(1.0, max(0.0, ((event.x - first[0]) * dx + (event.y - first[1]) * dy) / length2))
                    point = (first[0] + fraction * dx, first[1] + fraction * dy)
                    distance = (point[0] - event.x) ** 2 + (point[1] - event.y) ** 2
                    if distance < nearest_distance:
                        nearest, nearest_distance = point, distance
                if nearest_distance > 100:
                    return
        px, py = nearest
        width, height = self.graph.winfo_width(), self.graph.winfo_height()
        x, y = self.viewport.screen_to_world(px, py, width, height)
        self.graph.create_oval(px - 4, py - 4, px + 4, py + 4, fill=self.theme.graph_background, outline=self.theme.text, width=2, tags="hover")
        self.graph.create_text(px + 8, py - 8, text=f"({x:.5g}, {y:.5g})", anchor="sw", fill=self.theme.text, font=("TkDefaultFont", 9), tags="hover")

    def _leave_graph(self, _event: tk.Event) -> None:
        self.graph.delete("hover")

    def _watch_theme(self) -> None:
        current_mtime = theme_mtime(self._theme_path)
        if current_mtime != self._theme_mtime:
            self.reload_theme()
        self.root.after(1200, self._watch_theme)

    def reload_theme(self, event: tk.Event | None = None) -> str | None:
        self.theme = load_theme(self._theme_path)
        self._theme_mtime = theme_mtime(self._theme_path)
        self.root.configure(background=self.theme.background)
        self.panes.configure(background=self.theme.divider)
        self._apply_widget_theme(self.root)
        self.graph_controls.configure(background=self.theme.graph_background)
        for button in self.graph_control_buttons:
            button.set_colors(self.theme.graph_background, self.theme.muted, self.theme.button_active, self.theme.text)
        for index, item in enumerate(self.rows):
            item.color = self.theme.curves[index % len(self.theme.curves)]
            item.marker.configure(foreground=item.color if item.enabled else self.theme.hidden_dot)
            item.answer.configure(foreground=self.theme.muted)
            item.warning.configure(foreground=self.theme.error)
            if item.animate_button is not None:
                running = item.animation_job is not None
                item.animate_button.configure(
                    background=self.theme.background,
                    activebackground=self.theme.background,
                    foreground=item.color if running else self.theme.muted,
                    activeforeground=item.color,
                )
            if item.slider_settings_button is not None:
                item.slider_settings_button.configure(
                    background=self.theme.background,
                    activebackground=self.theme.background,
                    foreground=self.theme.muted,
                    activeforeground=self.theme.text,
                )
            for entry in (item.slider_min_entry, item.slider_max_entry, item.slider_step_entry):
                if entry is not None:
                    entry.configure(background=self.theme.button, foreground=self.theme.text, insertbackground=self.theme.text)
            if item.slider is not None:
                item.slider.set_colors(item.color, self.theme.background, self.theme.trough)
        self.schedule_redraw(0)
        return "break" if event is not None else None

    def _apply_widget_theme(self, widget: tk.Misc) -> None:
        """apply theme colors to tk widgets."""
        try:
            widget_class = widget.winfo_class()
            if isinstance(widget, IconButton):
                widget.set_colors(self.theme.graph_background, self.theme.muted, self.theme.button_active, self.theme.text)
            elif widget is self.graph:
                widget.configure(background=self.theme.graph_background)
            elif widget_class in ("Frame", "Panedwindow", "Toplevel"):
                widget.configure(background=self.theme.background)
            elif widget_class == "Canvas":
                widget.configure(background=self.theme.background)
            elif widget_class == "Entry":
                widget.configure(background=self.theme.background, foreground=self.theme.text, insertbackground=self.theme.text)
            elif widget_class == "Label":
                widget.configure(background=self.theme.background)
            elif widget_class == "Button":
                widget.configure(background=self.theme.button, foreground=self.theme.muted, activebackground=self.theme.button_active, activeforeground=self.theme.text)
            elif widget_class == "Scale":
                widget.configure(background=self.theme.background, troughcolor=self.theme.trough, activebackground=self.theme.button_active)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._apply_widget_theme(child)

    def _draw_grid(self, width: int, height: int) -> None:
        canvas = self.graph
        left, top = self.viewport.screen_to_world(0, 0, width, height)
        right, bottom = self.viewport.screen_to_world(width, height, width, height)
        axis_x, axis_y = self.viewport.world_to_screen(0, 0, width, height)
        label_y = min(float(height), max(0.0, axis_y))
        label_x = min(float(width), max(0.0, axis_x))
        x_label_anchor = "nw" if label_y < height - 14 else "sw"
        x_label_offset = 3 if x_label_anchor == "nw" else -3
        y_label_anchor = "nw" if label_x < width - 36 else "ne"
        y_label_offset = 4 if y_label_anchor == "nw" else -4
        x_step = nice_tick_step(right - left)
        y_step = nice_tick_step(top - bottom)
        first_x = int(left // x_step) - 1
        last_x = int(right // x_step) + 1
        first_y = int(bottom // y_step) - 1
        last_y = int(top // y_step) + 1
        for n in range(first_x, last_x + 1):
            x = n * x_step
            px, _ = self.viewport.world_to_screen(x, 0, width, height)
            is_axis = abs(x) < x_step * 1e-9
            canvas.create_line(px, 0, px, height, fill=self.theme.axis if is_axis else self.theme.grid, width=1, tags="scene")
            if not is_axis and 0 <= px <= width:
                canvas.create_text(px + 3, label_y + x_label_offset, text=self._format_tick(x), anchor=x_label_anchor, fill=self.theme.muted, font=("TkDefaultFont", 8), tags="scene")
        for n in range(first_y, last_y + 1):
            y = n * y_step
            _, py = self.viewport.world_to_screen(0, y, width, height)
            is_axis = abs(y) < y_step * 1e-9
            canvas.create_line(0, py, width, py, fill=self.theme.axis if is_axis else self.theme.grid, width=1, tags="scene")
            if not is_axis and 0 <= py <= height:
                canvas.create_text(label_x + y_label_offset, py - 2, text=self._format_tick(y), anchor=y_label_anchor, fill=self.theme.muted, font=("TkDefaultFont", 8), tags="scene")

    @staticmethod
    def _format_tick(value: float) -> str:
        return str(int(value)) if abs(value - round(value)) < 1e-8 else f"{value:g}"

    def _start_pan(self, event: tk.Event) -> None:
        self._invalidate_render()
        self._cancel_redraw()
        self.graph.delete("hover")
        self.drag_point = (event.x, event.y)
        self.graph.configure(cursor="fleur")

    def _pan(self, event: tk.Event) -> None:
        if self.drag_point is None:
            return
        old_x, old_y = self.drag_point
        dx, dy = event.x - old_x, event.y - old_y
        self.viewport.pan_pixels(dx, dy)
        self.graph.move("scene", dx, dy)
        self.intersection_points = [(x + dx, y + dy) for x, y in self.intersection_points]
        self.plot_points = [(x + dx, y + dy) for x, y in self.plot_points]
        self.root_points = [(x + dx, y + dy) for x, y in self.root_points]
        self.trace_segments = [((x1 + dx, y1 + dy), (x2 + dx, y2 + dy)) for (x1, y1), (x2, y2) in self.trace_segments]
        self.drag_point = (event.x, event.y)
        self._invalidate_render()
        self.schedule_live_redraw()

    def _end_pan(self, _event: tk.Event) -> None:
        self.drag_point = None
        self.graph.configure(cursor="")
        self.schedule_redraw(1)

    def _wheel_zoom(self, event: tk.Event) -> None:
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom_event(event, factor)

    def _zoom_event(self, event: tk.Event, factor: float) -> None:
        self._invalidate_render()
        self.graph.delete("hover")
        old_scale = self.viewport.scale
        self.viewport.zoom_at(factor, event.x, event.y, self.graph.winfo_width(), self.graph.winfo_height())
        actual_factor = self.viewport.scale / old_scale
        self.graph.scale("scene", event.x, event.y, actual_factor, actual_factor)
        self.intersection_points = [
            (event.x + (x - event.x) * actual_factor, event.y + (y - event.y) * actual_factor)
            for x, y in self.intersection_points
        ]
        self.plot_points = [
            (event.x + (x - event.x) * actual_factor, event.y + (y - event.y) * actual_factor)
            for x, y in self.plot_points
        ]
        self.root_points = [
            (event.x + (x - event.x) * actual_factor, event.y + (y - event.y) * actual_factor)
            for x, y in self.root_points
        ]
        self.trace_segments = [
            (
                (event.x + (x1 - event.x) * actual_factor, event.y + (y1 - event.y) * actual_factor),
                (event.x + (x2 - event.x) * actual_factor, event.y + (y2 - event.y) * actual_factor),
            )
            for (x1, y1), (x2, y2) in self.trace_segments
        ]
        self.schedule_live_redraw()

    def _cancel_redraw(self) -> None:
        if self.redraw_job is not None:
            self.root.after_cancel(self.redraw_job)
            self.redraw_job = None
        self.redraw_is_live = False

    def _project_data(self) -> dict:
        rows = []
        for item in self.rows:
            rows.append({
                "expression": item.entry.get(),
                "enabled": item.enabled,
                "slider_settings": list(item.slider_spec_override) if item.slider_spec_override is not None else None,
                "slider_value": item.slider.get() if item.slider is not None else None,
                "settings_open": item.slider_settings_open,
            })
        return {
            "format": "graf-project",
            "version": 1,
            "rows": rows,
            "viewport": {
                "center_x": self.viewport.center_x,
                "center_y": self.viewport.center_y,
                "scale": self.viewport.scale,
            },
        }

    def save_project(self, event: tk.Event | None = None) -> str | None:
        if self.project_path is None:
            return self.save_project_as(event)
        try:
            self.project_path.write_text(json.dumps(self._project_data(), indent=2) + "\n", encoding="utf-8")
            self.root.title(f"graf — {self.project_path.name}")
        except OSError as error:
            messagebox.showerror("Could not save project", str(error), parent=self.root)
        return "break" if event is not None else None

    def save_project_as(self, event: tk.Event | None = None) -> str | None:
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save graf project",
            defaultextension=".graf.json",
            filetypes=(("Graf project", "*.graf.json"), ("JSON", "*.json"), ("All files", "*")),
        )
        if selected:
            self.project_path = Path(selected)
            self.save_project()
        return "break" if event is not None else None

    def open_project(self, event: tk.Event | None = None) -> str | None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Open graf project",
            filetypes=(("Graf project", "*.graf.json"), ("JSON", "*.json"), ("All files", "*")),
        )
        if not selected:
            return "break" if event is not None else None
        path = Path(selected)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._load_project_data(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            messagebox.showerror("Could not open project", str(error), parent=self.root)
            return "break" if event is not None else None
        self.project_path = path
        self.root.title(f"graf — {path.name}")
        return "break" if event is not None else None

    def _load_project_data(self, data: object) -> None:
        if not isinstance(data, dict) or data.get("format") != "graf-project" or data.get("version") != 1:
            raise ValueError("This is not a supported graf project")
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Project rows are missing")

        # validate the whole file before touching the current project
        normalized_rows: list[dict[str, object]] = []
        for saved in rows or [{"expression": ""}]:
            if not isinstance(saved, dict):
                raise ValueError("A project row is invalid")
            expression = saved.get("expression", "")
            if not isinstance(expression, str):
                raise ValueError("A row expression must be text")
            slider_spec: tuple[float, float, float] | None = None
            settings = saved.get("slider_settings")
            if settings is not None:
                if not isinstance(settings, list) or len(settings) != 3:
                    raise ValueError("Slider settings must contain minimum, maximum, and step")
                try:
                    lower, upper, step = (float(value) for value in settings)
                except (TypeError, ValueError) as error:
                    raise ValueError("Slider settings must be numbers") from error
                if not all(math.isfinite(value) for value in (lower, upper, step)) or lower >= upper or step <= 0:
                    raise ValueError("Slider settings need minimum < maximum and step > 0")
                slider_spec = (lower, upper, step)
            slider_value: float | None = None
            value = saved.get("slider_value")
            if value is not None:
                try:
                    slider_value = float(value)
                except (TypeError, ValueError) as error:
                    raise ValueError("A slider value must be a number") from error
                if not math.isfinite(slider_value):
                    raise ValueError("A slider value must be finite")
            normalized_rows.append({
                "expression": expression,
                "enabled": bool(saved.get("enabled", False)),
                "slider_settings": slider_spec,
                "slider_value": slider_value,
                "settings_open": bool(saved.get("settings_open", False)),
            })

        loaded_viewport: Viewport | None = None
        viewport = data.get("viewport")
        if viewport is not None:
            if not isinstance(viewport, dict):
                raise ValueError("Project viewport is invalid")
            try:
                center_x = float(viewport.get("center_x", 0.0))
                center_y = float(viewport.get("center_y", 0.0))
                scale = float(viewport.get("scale", 48.0))
            except (TypeError, ValueError) as error:
                raise ValueError("Project viewport values must be numbers") from error
            if not all(math.isfinite(value) for value in (center_x, center_y, scale)) or scale <= 0:
                raise ValueError("Project viewport values are invalid")
            loaded_viewport = Viewport(
                center_x=center_x,
                center_y=center_y,
                scale=min(800.0, max(3.0, scale)),
            )

        for item in self.rows:
            self._clear_row_error(item)
            self._remove_slider(item)
            item.frame.destroy()
        self.rows.clear()
        for saved in normalized_rows:
            self.add_row(str(saved["expression"]), focus=False)
            item = self.rows[-1]
            item.enabled = bool(saved["enabled"])
            item.slider_spec_override = saved["slider_settings"]  # type: ignore[assignment]
            item.pending_slider_value = saved["slider_value"]  # type: ignore[assignment]
            item.slider_settings_open = bool(saved["settings_open"])
        if loaded_viewport is not None:
            self.viewport = loaded_viewport
        self.render_cache.clear()
        self.queued_render_request = None
        self._recolor_rows()
        self.rows[0].entry.focus_set()
        self._invalidate_render()
        self.schedule_redraw(0)

    def reset_view(self, event: tk.Event | None = None) -> str | None:
        self._cancel_redraw()
        self._invalidate_render()
        self.viewport = Viewport()
        self.graph.delete("hover")
        self.schedule_redraw(0)
        return "break" if event is not None else None

    def _close(self) -> None:
        self.render_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def run() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = tk.Tk()
    GraphApp(root)
    root.mainloop()
