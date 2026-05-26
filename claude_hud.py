"""
Claude Code Usage HUD
Floating always-on-top window showing token usage, % of session limit, and reset time.
Right-click to close. Drag to move.
"""

import tkinter as tk
import json
import os
import glob
import sys
import socket
from datetime import datetime, timezone, timedelta

# Single-instance guard via a local TCP port lock
_LOCK_PORT = 47291
_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
except OSError:
    sys.exit(0)

CLAUDE_DIR   = os.path.expanduser("~/.claude")
WINDOW_HOURS = 5          # Claude Code rolling usage window
REFRESH_MS   = 15_000     # refresh every 15 seconds

# Approximate output-token limit per 5h window for your plan.
# Adjust if you hit limits earlier/later. (Pro ≈ 1M, Max 5x ≈ 5M)
OUTPUT_LIMIT = 2_000_000


# ---------- data ----------

def get_usage():
    now          = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=WINDOW_HOURS)

    totals = dict(input=0, cache_creation=0, cache_read=0, output=0)
    oldest = None

    pattern = os.path.join(CLAUDE_DIR, "projects", "**", "*.jsonl")
    for path in glob.glob(pattern, recursive=True):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    ts_str = obj.get("timestamp")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < window_start:
                        continue
                    usage = obj.get("message", {}).get("usage", {})
                    if not usage:
                        continue
                    totals["input"]          += usage.get("input_tokens", 0)
                    totals["cache_creation"] += usage.get("cache_creation_input_tokens", 0)
                    totals["cache_read"]     += usage.get("cache_read_input_tokens", 0)
                    totals["output"]         += usage.get("output_tokens", 0)
                    if oldest is None or ts < oldest:
                        oldest = ts
        except Exception:
            pass

    reset_at = (oldest + timedelta(hours=WINDOW_HOURS)) if oldest else None
    return totals, reset_at, now


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def fmt_countdown(reset_at, now):
    if reset_at is None:
        return "no activity"
    delta = reset_at - now
    if delta.total_seconds() <= 0:
        return "now"
    m, s = divmod(int(delta.total_seconds()), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


# ---------- theme ----------

BG      = "#0d1117"
HDR_BG  = "#161b22"
SEP     = "#21262d"
ACCENT  = "#58a6ff"
DIM     = "#8b949e"
WHITE   = "#e6edf3"
GREEN   = "#3fb950"
YELLOW  = "#d29922"
RED     = "#f85149"
FOOTER  = "#484f58"

F_TITLE = ("Consolas", 10, "bold")
F_ROW   = ("Consolas", 9)
F_FOOT  = ("Consolas", 8)

BAR_W   = 190
BAR_H   = 6


def bar_color(pct):
    if pct < 60:
        return GREEN
    if pct < 85:
        return YELLOW
    return RED


# ---------- HUD ----------

class HUD(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Claude HUD")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg=BG)

        self._drag_x = self._drag_y = 0
        self._build_ui()

        self.bind("<ButtonPress-1>", self._drag_start)
        self.bind("<B1-Motion>",     self._drag_move)
        self.bind("<ButtonPress-3>", lambda e: self.destroy())

        # Position: top-right corner, 20px from edge
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"+{sw - 240}+20")

        self._refresh()

    # ---- layout ----

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=HDR_BG, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  Claude Code Usage", bg=HDR_BG,
                 fg=ACCENT, font=F_TITLE, anchor="w").pack(fill="x", padx=8)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="x", padx=10, pady=4)

        def sep():
            tk.Frame(body, bg=SEP, height=1).pack(fill="x", pady=3)

        def row(label, var, color=WHITE):
            f = tk.Frame(body, bg=BG)
            f.pack(fill="x", pady=1)
            tk.Label(f, text=label, bg=BG, fg=DIM,
                     font=F_ROW, anchor="w", width=12).pack(side="left")
            tk.Label(f, textvariable=var, bg=BG,
                     fg=color, font=F_ROW, anchor="e", width=9).pack(side="right")

        self.v_input   = tk.StringVar()
        self.v_output  = tk.StringVar()
        self.v_total   = tk.StringVar()
        self.v_pct     = tk.StringVar()
        self.v_reset   = tk.StringVar()
        self.v_updated = tk.StringVar()

        sep()
        row("Input",  self.v_input,  WHITE)
        row("Output", self.v_output, GREEN)
        sep()
        row("Total 5h",     self.v_total,   ACCENT)

        # Progress bar row
        pbar_frame = tk.Frame(body, bg=BG)
        pbar_frame.pack(fill="x", pady=2)
        tk.Label(pbar_frame, text="Usage %", bg=BG, fg=DIM,
                 font=F_ROW, anchor="w", width=12).pack(side="left")
        tk.Label(pbar_frame, textvariable=self.v_pct, bg=BG,
                 fg=WHITE, font=F_ROW, anchor="e", width=9).pack(side="right")

        bar_outer = tk.Frame(body, bg=SEP, height=BAR_H + 2)
        bar_outer.pack(fill="x", pady=(1, 4))
        bar_outer.pack_propagate(False)
        self._bar_canvas = tk.Canvas(bar_outer, bg=SEP, height=BAR_H,
                                     highlightthickness=0)
        self._bar_canvas.pack(fill="x", padx=1, pady=1)

        sep()
        row("Reset in",     self.v_reset,   YELLOW)

        # Footer
        foot = tk.Frame(self, bg=BG, pady=2)
        foot.pack(fill="x")
        tk.Label(foot, textvariable=self.v_updated, bg=BG,
                 fg=FOOTER, font=F_FOOT, anchor="e").pack(fill="x", padx=10)

    # ---- refresh ----

    def _refresh(self):
        totals, reset_at, now = get_usage()
        total = (totals["input"] + totals["cache_creation"]
                 + totals["cache_read"] + totals["output"])
        pct = min(totals["output"] / OUTPUT_LIMIT * 100, 100) if OUTPUT_LIMIT else 0

        self.v_input.set(fmt_tokens(totals["input"]))
        self.v_output.set(fmt_tokens(totals["output"]))
        self.v_total.set(fmt_tokens(total))
        self.v_pct.set(f"{pct:.1f}%")
        self.v_reset.set(fmt_countdown(reset_at, now))
        self.v_updated.set(f"updated {now.strftime('%H:%M:%S')} UTC")

        self._draw_bar(pct)
        self.after(REFRESH_MS, self._refresh)

    def _draw_bar(self, pct):
        c = self._bar_canvas
        c.update_idletasks()
        w = c.winfo_width()
        if w < 2:
            w = BAR_W
        c.delete("all")
        filled = int(w * pct / 100)
        if filled > 0:
            c.create_rectangle(0, 0, filled, BAR_H,
                                fill=bar_color(pct), outline="")

    # ---- drag ----

    def _drag_start(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _drag_move(self, e):
        x = self.winfo_x() + e.x - self._drag_x
        y = self.winfo_y() + e.y - self._drag_y
        self.geometry(f"+{x}+{y}")


if __name__ == "__main__":
    HUD().mainloop()
