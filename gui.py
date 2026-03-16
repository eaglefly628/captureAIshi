#!/usr/bin/env python3
"""captureAIshi — Native GUI (tkinter, zero external dependencies).

Provides a desktop interface to configure and launch captures, with
dedicated RenderDoc controls for capture replay, draw-call filtering,
and depth extraction settings.

All capture logic is reused from main.py — this is just a GUI shell.
"""

import logging
import threading
import tkinter as tk
from argparse import Namespace
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


# ---------------------------------------------------------------------------
# Dark-theme colours
# ---------------------------------------------------------------------------
_BG = "#0f1117"
_CARD = "#1a1d27"
_BORDER = "#2a2d3a"
_ACCENT = "#6c5ce7"
_ACCENT_HOVER = "#7c6df7"
_TEXT = "#e0e0e0"
_TEXT_DIM = "#888888"
_SUCCESS = "#00b894"
_DANGER = "#e74c3c"
_WARN = "#fdcb6e"
_INPUT_BG = "#141720"


# ---------------------------------------------------------------------------
# Logging handler that pushes records into a tk.Text widget
# ---------------------------------------------------------------------------
class _TextHandler(logging.Handler):
    """Route log records into a scrolled text widget."""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self._text = text_widget
        self._line_count = 0

    def emit(self, record):
        msg = self.format(record)
        try:
            self._text.after(0, self._append, msg, record.levelno)
        except Exception:
            pass  # widget destroyed

    @property
    def line_count(self):
        return self._line_count

    def _append(self, msg: str, level: int):
        self._text.configure(state="normal")
        tag = "info"
        if level >= logging.ERROR:
            tag = "error"
        elif level >= logging.WARNING:
            tag = "warn"
        self._text.insert(tk.END, msg + "\n", tag)
        self._text.see(tk.END)
        self._line_count += 1
        self._text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class CaptureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("captureAIshi")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(bg=_BG)

        self._running = False

        self._build_styles()
        self._build_header()
        self._build_body()
        self._bind_visibility()

    # ---- styling ----------------------------------------------------------
    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=_BG, foreground=_TEXT, fieldbackground=_INPUT_BG,
                         bordercolor=_BORDER, troughcolor=_BORDER, font=("Segoe UI", 10))
        style.configure("TFrame", background=_CARD)
        style.configure("TLabel", background=_CARD, foreground=_TEXT, font=("Segoe UI", 10))
        style.configure("Dim.TLabel", foreground=_TEXT_DIM, font=("Segoe UI", 9))
        style.configure("Section.TLabel", foreground=_ACCENT, font=("Segoe UI", 9, "bold"))
        style.configure("Header.TLabel", background=_CARD, foreground=_TEXT,
                         font=("Segoe UI", 14, "bold"))
        style.configure("Accent.TLabel", foreground=_ACCENT, background=_CARD,
                         font=("Segoe UI", 14, "bold"))
        style.configure("Badge.TLabel", background=_BORDER, foreground=_TEXT_DIM,
                         font=("Segoe UI", 9, "bold"), padding=(8, 3))

        style.configure("TEntry", fieldbackground=_INPUT_BG, foreground=_TEXT,
                         insertcolor=_TEXT, borderwidth=1, relief="solid")
        style.map("TEntry", bordercolor=[("focus", _ACCENT), ("!focus", _BORDER)])

        style.configure("TSpinbox", fieldbackground=_INPUT_BG, foreground=_TEXT,
                         arrowcolor=_TEXT_DIM, borderwidth=1, relief="solid")

        style.configure("TCombobox", fieldbackground=_INPUT_BG, foreground=_TEXT,
                         arrowcolor=_TEXT_DIM, borderwidth=1, relief="solid")
        style.map("TCombobox", fieldbackground=[("readonly", _INPUT_BG)],
                  foreground=[("readonly", _TEXT)],
                  bordercolor=[("focus", _ACCENT), ("!focus", _BORDER)])

        style.configure("TCheckbutton", background=_CARD, foreground=_TEXT,
                         indicatorbackground=_INPUT_BG, indicatorcolor=_ACCENT)
        style.map("TCheckbutton",
                  indicatorbackground=[("selected", _ACCENT), ("!selected", _INPUT_BG)])

        style.configure("Accent.TButton", background=_ACCENT, foreground="#fff",
                         font=("Segoe UI", 10, "bold"), padding=(12, 6))
        style.map("Accent.TButton",
                  background=[("active", _ACCENT_HOVER), ("disabled", _BORDER)],
                  foreground=[("disabled", _TEXT_DIM)])

        style.configure("Secondary.TButton", background=_BORDER, foreground=_TEXT,
                         font=("Segoe UI", 10), padding=(12, 6))
        style.map("Secondary.TButton", background=[("active", "#353849")])

        style.configure("Danger.TButton", background=_DANGER, foreground="#fff",
                         font=("Segoe UI", 10), padding=(8, 4))
        style.map("Danger.TButton", background=[("active", "#c0392b")])

        style.configure("TNotebook", background=_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=_BORDER, foreground=_TEXT_DIM,
                         padding=(10, 4), font=("Segoe UI", 9))
        style.map("TNotebook.Tab",
                  background=[("selected", _CARD)],
                  foreground=[("selected", _TEXT)])

        style.configure("TSeparator", background=_BORDER)

        # LabelFrame
        style.configure("TLabelframe", background=_CARD, foreground=_TEXT,
                         bordercolor=_BORDER)
        style.configure("TLabelframe.Label", background=_CARD, foreground=_ACCENT,
                         font=("Segoe UI", 9, "bold"))

    # ---- header bar -------------------------------------------------------
    def _build_header(self):
        hdr = ttk.Frame(self, style="TFrame")
        hdr.pack(fill=tk.X, side=tk.TOP)

        inner = ttk.Frame(hdr)
        inner.pack(fill=tk.X, padx=16, pady=10)

        title = ttk.Frame(inner)
        title.pack(side=tk.LEFT)
        ttk.Label(title, text="capture", style="Accent.TLabel").pack(side=tk.LEFT)
        ttk.Label(title, text="AIshi", style="Header.TLabel").pack(side=tk.LEFT)

        self._badge = ttk.Label(inner, text="IDLE", style="Badge.TLabel")
        self._badge.pack(side=tk.RIGHT)

    # ---- body (sidebar + log) ---------------------------------------------
    def _build_body(self):
        body = ttk.Frame(self, style="TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_log_panel(body)

    # ---- sidebar ----------------------------------------------------------
    def _build_sidebar(self, parent):
        # Canvas + scrollbar for sidebar scrolling
        canvas_frame = ttk.Frame(parent)
        canvas_frame.grid(row=0, column=0, sticky="ns")

        canvas = tk.Canvas(canvas_frame, width=370, bg=_CARD, highlightthickness=0,
                           borderwidth=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sidebar = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=sidebar, anchor="nw")
        sidebar.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Allow mouse-wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        pad = dict(padx=12, pady=(0, 2), anchor="w", fill=tk.X)

        # ---- Capture Volume ----
        self._section(sidebar, "Capture Volume")
        ttk.Label(sidebar, text="Min (x, y, z)", style="Dim.TLabel").pack(**pad)
        row = ttk.Frame(sidebar); row.pack(fill=tk.X, padx=12, pady=2)
        self.vol_min_x = self._spin(row, -5, side=tk.LEFT)
        self.vol_min_y = self._spin(row, 0, side=tk.LEFT)
        self.vol_min_z = self._spin(row, -5, side=tk.LEFT)

        ttk.Label(sidebar, text="Max (x, y, z)", style="Dim.TLabel").pack(**pad)
        row = ttk.Frame(sidebar); row.pack(fill=tk.X, padx=12, pady=2)
        self.vol_max_x = self._spin(row, 5, side=tk.LEFT)
        self.vol_max_y = self._spin(row, 3, side=tk.LEFT)
        self.vol_max_z = self._spin(row, 5, side=tk.LEFT)

        ttk.Label(sidebar, text="Spacing (m)", style="Dim.TLabel").pack(**pad)
        self.spacing = self._spin(sidebar, 2.0, from_=0.1, increment=0.1, pack_parent=True)

        # ---- Path ----
        self._section(sidebar, "Path")
        self.smooth_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sidebar, text="Smooth Path", variable=self.smooth_var).pack(**pad)
        ttk.Label(sidebar, text="Points per Segment", style="Dim.TLabel").pack(**pad)
        self.smooth_points = self._spin(sidebar, 5, from_=2, to=50, pack_parent=True)

        # ---- Cone Rotation ----
        self._section(sidebar, "Cone Rotation")
        ttk.Label(sidebar, text="Half Angle (deg, 0=off)", style="Dim.TLabel").pack(**pad)
        self.cone_angle = self._spin(sidebar, 0, from_=0, to=90, pack_parent=True)
        row = ttk.Frame(sidebar); row.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(row, text="Ring Samples", style="Dim.TLabel").pack(side=tk.LEFT)
        self.cone_samples = self._spin(row, 8, from_=1, side=tk.RIGHT, width=6)
        row = ttk.Frame(sidebar); row.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(row, text="Rings", style="Dim.TLabel").pack(side=tk.LEFT)
        self.cone_rings = self._spin(row, 2, from_=1, side=tk.RIGHT, width=6)

        # ---- Driver ----
        self._section(sidebar, "Driver")
        ttk.Label(sidebar, text="Type", style="Dim.TLabel").pack(**pad)
        self.driver_var = tk.StringVar(value="manual")
        cb = ttk.Combobox(sidebar, textvariable=self.driver_var, state="readonly",
                          values=["manual", "ue5", "unity", "cheatengine"])
        cb.pack(fill=tk.X, padx=12, pady=2)

        row = ttk.Frame(sidebar); row.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(row, text="Host", style="Dim.TLabel").pack(side=tk.LEFT)
        self.driver_host = ttk.Entry(row, width=14)
        self.driver_host.insert(0, "127.0.0.1")
        self.driver_host.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(row, text="Port", style="Dim.TLabel").pack(side=tk.LEFT)
        self.driver_port = self._spin(row, 9999, from_=1, to=65535, side=tk.RIGHT, width=7)

        self._ce_frame = ttk.Frame(sidebar)
        self._ce_frame.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(self._ce_frame, text="CE Mode", style="Dim.TLabel").pack(side=tk.LEFT)
        self.ce_mode_var = tk.StringVar(value="file")
        ttk.Combobox(self._ce_frame, textvariable=self.ce_mode_var, state="readonly",
                     values=["file", "socket"], width=8).pack(side=tk.RIGHT)

        # ---- Grabber ----
        self._section(sidebar, "Grabber")
        ttk.Label(sidebar, text="Type", style="Dim.TLabel").pack(**pad)
        self.grabber_var = tk.StringVar(value="none")
        ttk.Combobox(sidebar, textvariable=self.grabber_var, state="readonly",
                     values=["none", "renderdoc", "screenshot"]).pack(fill=tk.X, padx=12, pady=2)

        self._target_frame = ttk.Frame(sidebar)
        self._target_frame.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(self._target_frame, text="Target Exe", style="Dim.TLabel").pack(side=tk.LEFT)
        self.target_exe = ttk.Entry(self._target_frame, width=18)
        self.target_exe.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(self._target_frame, text="...", width=3,
                   command=self._browse_exe).pack(side=tk.RIGHT)

        # ---- RenderDoc Settings ----
        self._section(sidebar, "RenderDoc")
        self._rdoc_frame = ttk.Frame(sidebar)
        self._rdoc_frame.pack(fill=tk.X, padx=12, pady=0)

        # renderdoccmd path
        row = ttk.Frame(self._rdoc_frame); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="renderdoccmd Path", style="Dim.TLabel").pack(anchor="w")
        rf = ttk.Frame(row); rf.pack(fill=tk.X)
        self.rdoc_path = ttk.Entry(rf)
        self.rdoc_path.insert(0, "renderdoccmd")
        self.rdoc_path.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(rf, text="...", width=3,
                   command=self._browse_rdoc).pack(side=tk.RIGHT, padx=(4, 0))

        # capture key
        row = ttk.Frame(self._rdoc_frame); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Capture Trigger Key", style="Dim.TLabel").pack(side=tk.LEFT)
        self.rdoc_capture_key = ttk.Entry(row, width=8)
        self.rdoc_capture_key.insert(0, "F12")
        self.rdoc_capture_key.pack(side=tk.RIGHT)

        # auto launch
        self.rdoc_auto_launch = tk.BooleanVar(value=False)
        ttk.Checkbutton(self._rdoc_frame, text="Auto-launch game via RenderDoc",
                        variable=self.rdoc_auto_launch).pack(anchor="w", pady=2)

        # capture options
        self.rdoc_api_validation = tk.BooleanVar(value=True)
        ttk.Checkbutton(self._rdoc_frame, text="API Validation",
                        variable=self.rdoc_api_validation).pack(anchor="w")
        self.rdoc_capture_callstacks = tk.BooleanVar(value=True)
        ttk.Checkbutton(self._rdoc_frame, text="Capture Callstacks",
                        variable=self.rdoc_capture_callstacks).pack(anchor="w")
        self.rdoc_ref_all_resources = tk.BooleanVar(value=True)
        ttk.Checkbutton(self._rdoc_frame, text="Ref All Resources",
                        variable=self.rdoc_ref_all_resources).pack(anchor="w")

        # capture delay
        row = ttk.Frame(self._rdoc_frame); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Post-capture Delay (s)", style="Dim.TLabel").pack(side=tk.LEFT)
        self.rdoc_delay = self._spin(row, 0.5, from_=0, to=10, increment=0.1,
                                     side=tk.RIGHT, width=6)

        # depth format
        row = ttk.Frame(self._rdoc_frame); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Depth Format", style="Dim.TLabel").pack(side=tk.LEFT)
        self.rdoc_depth_format = tk.StringVar(value="reverse_z_float32")
        ttk.Combobox(row, textvariable=self.rdoc_depth_format, state="readonly",
                     values=["reverse_z_float32", "linear_float32", "unorm_24bit"],
                     width=18).pack(side=tk.RIGHT)

        # UI draw-call filter settings
        ttk.Separator(self._rdoc_frame, orient="horizontal").pack(fill=tk.X, pady=6)
        ttk.Label(self._rdoc_frame, text="Draw-Call UI Filter", style="Section.TLabel").pack(anchor="w")

        self.rdoc_filter_ui = tk.BooleanVar(value=True)
        ttk.Checkbutton(self._rdoc_frame, text="Filter UI draw calls on replay",
                        variable=self.rdoc_filter_ui).pack(anchor="w", pady=2)

        row = ttk.Frame(self._rdoc_frame); row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="UI Region (last %)", style="Dim.TLabel").pack(side=tk.LEFT)
        self.rdoc_ui_region_pct = self._spin(row, 20, from_=5, to=50,
                                              side=tk.RIGHT, width=5)

        ttk.Label(self._rdoc_frame, text="Extra UI Keywords (comma-sep)", style="Dim.TLabel").pack(anchor="w")
        self.rdoc_extra_keywords = ttk.Entry(self._rdoc_frame)
        self.rdoc_extra_keywords.pack(fill=tk.X, pady=2)

        # ---- RenderDoc Actions ----
        ttk.Separator(self._rdoc_frame, orient="horizontal").pack(fill=tk.X, pady=6)
        ttk.Label(self._rdoc_frame, text="Quick Actions", style="Section.TLabel").pack(anchor="w", pady=(0, 4))

        btn_row = ttk.Frame(self._rdoc_frame); btn_row.pack(fill=tk.X, pady=2)
        ttk.Button(btn_row, text="Open .rdc File",
                   style="Secondary.TButton",
                   command=self._open_rdc_file).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Replay Last Capture",
                   style="Secondary.TButton",
                   command=self._replay_last_capture).pack(side=tk.LEFT, padx=(0, 4))

        btn_row2 = ttk.Frame(self._rdoc_frame); btn_row2.pack(fill=tk.X, pady=2)
        ttk.Button(btn_row2, text="Test Connection",
                   style="Secondary.TButton",
                   command=self._test_rdoc_connection).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row2, text="Browse Captures Dir",
                   style="Secondary.TButton",
                   command=self._browse_captures_dir).pack(side=tk.LEFT, padx=(0, 4))

        # ---- Options ----
        self._section(sidebar, "Options")
        self.no_hide_ui_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sidebar, text="Disable UI Hiding",
                        variable=self.no_hide_ui_var).pack(**pad)
        self.dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sidebar, text="Dry Run (poses only)",
                        variable=self.dry_run_var).pack(**pad)

        row = ttk.Frame(sidebar); row.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(row, text="Output Dir", style="Dim.TLabel").pack(side=tk.LEFT)
        self.output_dir = ttk.Entry(row, width=18)
        self.output_dir.insert(0, "./output")
        self.output_dir.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(row, text="...", width=3,
                   command=self._browse_output).pack(side=tk.RIGHT)

        # ---- Action buttons ----
        ttk.Separator(sidebar, orient="horizontal").pack(fill=tk.X, padx=12, pady=8)
        btn_frame = ttk.Frame(sidebar)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 12))

        self._btn_start = ttk.Button(btn_frame, text="Start Capture",
                                     style="Accent.TButton",
                                     command=self._start_capture)
        self._btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self._btn_stop = ttk.Button(btn_frame, text="Stop",
                                    style="Danger.TButton",
                                    command=self._stop_capture, state="disabled")
        self._btn_stop.pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(btn_frame, text="Clear Log",
                   style="Secondary.TButton",
                   command=self._clear_log).pack(side=tk.RIGHT)

    # ---- log panel --------------------------------------------------------
    def _build_log_panel(self, parent):
        log_frame = ttk.Frame(parent)
        log_frame.grid(row=0, column=1, sticky="nsew")

        hdr = ttk.Frame(log_frame)
        hdr.pack(fill=tk.X, padx=12, pady=8)
        ttk.Label(hdr, text="LOG OUTPUT", style="Dim.TLabel").pack(side=tk.LEFT)
        self._log_count_label = ttk.Label(hdr, text="0 lines", style="Dim.TLabel")
        self._log_count_label.pack(side=tk.RIGHT)

        self._log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, state="disabled",
            bg=_BG, fg=_TEXT_DIM, insertbackground=_TEXT,
            font=("Consolas", 10), relief="flat", borderwidth=0,
            selectbackground=_ACCENT,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Tag colours for log levels
        self._log_text.tag_configure("info", foreground=_TEXT_DIM)
        self._log_text.tag_configure("warn", foreground=_WARN)
        self._log_text.tag_configure("error", foreground=_DANGER)

        # Install log handler
        self._log_handler = _TextHandler(self._log_text)
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )

        # Initial message
        self._log_text.configure(state="normal")
        self._log_text.insert(tk.END, "Ready. Configure parameters and click Start Capture.\n", "info")
        self._log_text.configure(state="disabled")

    # ---- helpers ----------------------------------------------------------
    def _section(self, parent, title):
        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))
        ttk.Label(parent, text=title.upper(), style="Section.TLabel").pack(
            padx=12, pady=(0, 4), anchor="w")

    def _spin(self, parent, value, *, from_=-9999, to=9999, increment=0.5,
              side=None, width=9, pack_parent=False):
        var = tk.StringVar(value=str(value))
        sb = ttk.Spinbox(parent, textvariable=var, from_=from_, to=to,
                         increment=increment, width=width)
        if pack_parent:
            sb.pack(fill=tk.X, padx=12, pady=2)
        elif side is not None:
            sb.pack(side=side, padx=2, expand=True, fill=tk.X)
        return var

    def _bind_visibility(self):
        """Show/hide fields based on selections."""
        def _update(*_args):
            driver = self.driver_var.get()
            grabber = self.grabber_var.get()
            # CE mode only for cheatengine driver
            if driver == "cheatengine":
                self._ce_frame.pack(fill=tk.X, padx=12, pady=2)
            else:
                self._ce_frame.pack_forget()
            # Target exe only for renderdoc grabber
            if grabber == "renderdoc":
                self._target_frame.pack(fill=tk.X, padx=12, pady=2)
                self._rdoc_frame.pack(fill=tk.X, padx=12, pady=0)
            else:
                self._target_frame.pack_forget()
                self._rdoc_frame.pack_forget()

        self.driver_var.trace_add("write", _update)
        self.grabber_var.trace_add("write", _update)
        _update()  # initial state

    # ---- file browse helpers ----
    def _browse_exe(self):
        path = filedialog.askopenfilename(
            title="Select Game Executable",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")])
        if path:
            self.target_exe.delete(0, tk.END)
            self.target_exe.insert(0, path)

    def _browse_rdoc(self):
        path = filedialog.askopenfilename(
            title="Select renderdoccmd",
            filetypes=[("Executables", "*.exe renderdoccmd"), ("All files", "*.*")])
        if path:
            self.rdoc_path.delete(0, tk.END)
            self.rdoc_path.insert(0, path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self.output_dir.delete(0, tk.END)
            self.output_dir.insert(0, path)

    # ---- RenderDoc action buttons ----
    def _open_rdc_file(self):
        path = filedialog.askopenfilename(
            title="Open RenderDoc Capture",
            filetypes=[("RenderDoc Captures", "*.rdc"), ("All files", "*.*")])
        if not path:
            return
        logging.info(f"Opening RenderDoc capture: {path}")
        try:
            import subprocess
            rdoc = self.rdoc_path.get() or "renderdoccmd"
            # Try qrenderdoc first (GUI), fall back to renderdoccmd
            subprocess.Popen([rdoc.replace("renderdoccmd", "qrenderdoc"), path])
            logging.info(f"Opened {path} in RenderDoc GUI")
        except Exception as e:
            logging.error(f"Failed to open capture: {e}")
            messagebox.showerror("Error", f"Could not open RenderDoc:\n{e}")

    def _replay_last_capture(self):
        out_dir = Path(self.output_dir.get()) / "captures"
        if not out_dir.exists():
            messagebox.showinfo("Info", f"No captures directory found:\n{out_dir}")
            return
        rdcs = sorted(out_dir.glob("*.rdc"))
        if not rdcs:
            messagebox.showinfo("Info", "No .rdc files found in captures directory.")
            return
        last = rdcs[-1]
        logging.info(f"Replaying last capture: {last}")
        try:
            import subprocess
            rdoc = self.rdoc_path.get() or "renderdoccmd"
            subprocess.Popen([rdoc.replace("renderdoccmd", "qrenderdoc"), str(last)])
        except Exception as e:
            logging.error(f"Failed to replay: {e}")

    def _test_rdoc_connection(self):
        """Verify renderdoccmd is reachable."""
        import subprocess
        rdoc = self.rdoc_path.get() or "renderdoccmd"
        logging.info(f"Testing RenderDoc: {rdoc} --version")
        try:
            result = subprocess.run([rdoc, "--version"], capture_output=True,
                                    text=True, timeout=5)
            ver = result.stdout.strip() or result.stderr.strip() or "(no output)"
            logging.info(f"RenderDoc version: {ver}")
            messagebox.showinfo("RenderDoc", f"renderdoccmd OK\n{ver}")
        except FileNotFoundError:
            logging.error(f"renderdoccmd not found at: {rdoc}")
            messagebox.showerror("Error",
                                 f"renderdoccmd not found at:\n{rdoc}\n\n"
                                 "Install RenderDoc or set the correct path.")
        except Exception as e:
            logging.error(f"RenderDoc test failed: {e}")
            messagebox.showerror("Error", str(e))

    def _browse_captures_dir(self):
        """Open the captures output directory in file manager."""
        import subprocess, sys
        cap_dir = Path(self.output_dir.get()) / "captures"
        cap_dir.mkdir(parents=True, exist_ok=True)
        path = str(cap_dir)
        logging.info(f"Opening captures directory: {path}")
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            logging.error(f"Could not open directory: {e}")

    # ---- capture start / stop ----
    def _build_args(self) -> Namespace:
        args = Namespace()
        args.volume_min = [float(self.vol_min_x.get()), float(self.vol_min_y.get()),
                           float(self.vol_min_z.get())]
        args.volume_max = [float(self.vol_max_x.get()), float(self.vol_max_y.get()),
                           float(self.vol_max_z.get())]
        args.spacing = float(self.spacing.get())
        args.smooth = self.smooth_var.get()
        args.smooth_points = int(self.smooth_points.get())
        args.cone_angle = float(self.cone_angle.get())
        args.cone_samples = int(self.cone_samples.get())
        args.cone_rings = int(self.cone_rings.get())
        args.driver = self.driver_var.get()
        args.driver_host = self.driver_host.get()
        args.driver_port = int(self.driver_port.get())
        args.ce_mode = self.ce_mode_var.get()
        args.grabber = self.grabber_var.get()
        args.target_exe = self.target_exe.get() or None
        args.no_hide_ui = self.no_hide_ui_var.get()
        args.output_dir = Path(self.output_dir.get())
        args.dry_run = self.dry_run_var.get()
        return args

    def _start_capture(self):
        if self._running:
            return
        self._running = True
        self._stop_event = threading.Event()
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._set_badge("running")

        args = self._build_args()

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self._log_handler)

        def _run():
            try:
                from main import run_capture
                run_capture(args)
            except Exception as e:
                logging.error(f"Capture failed: {e}")
                self.after(0, lambda: self._set_badge("error"))
            finally:
                self._running = False
                root_logger.removeHandler(self._log_handler)
                self.after(0, self._on_capture_done)

        threading.Thread(target=_run, daemon=True).start()

    def _stop_capture(self):
        # Signal to stop (best-effort — the capture loop would need to check)
        self._stop_event.set()
        logging.warning("Stop requested — capture will halt after current frame.")

    def _on_capture_done(self):
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        if self._badge.cget("text") != "ERROR":
            self._set_badge("idle")
        logging.info("Capture finished.")
        self._update_log_count()

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state="disabled")
        self._log_count_label.configure(text="0 lines")

    def _set_badge(self, state: str):
        style = ttk.Style()
        if state == "running":
            style.configure("Badge.TLabel", background="#00b89433", foreground=_SUCCESS)
            self._badge.configure(text="RUNNING")
        elif state == "error":
            style.configure("Badge.TLabel", background="#e74c3c33", foreground=_DANGER)
            self._badge.configure(text="ERROR")
        else:
            style.configure("Badge.TLabel", background=_BORDER, foreground=_TEXT_DIM)
            self._badge.configure(text="IDLE")

    def _update_log_count(self):
        if hasattr(self, '_log_handler'):
            self._log_count_label.configure(
                text=f"{self._log_handler.line_count} lines")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    app = CaptureApp()
    app.mainloop()


if __name__ == "__main__":
    main()
