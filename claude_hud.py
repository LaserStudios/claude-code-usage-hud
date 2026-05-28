"""
Claude Code Usage HUD
Floating always-on-top window showing token usage, % of session limit, and reset time.
Right-click to close. Drag to move. Click plan buttons to switch plans.
"""

import tkinter as tk
import json
import os
import glob
import sys
import socket
from datetime import datetime, timezone, timedelta

# ---------- single-instance guard ----------
_LOCK_PORT = 47291
_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
except OSError:
    sys.exit(0)

# ---------- constants ----------
CLAUDE_DIR   = os.path.expanduser("~/.claude")
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(SCRIPT_DIR, "hud_config.json")
WINDOW_HOURS = 5
REFRESH_MS   = 10_000

# Cost limit per 5h window per plan (USD, estimated from token pricing)
# Based on: Pro session at 90% ≈ $16.69 → limit ≈ $18.54
PLANS = {
    "Free":  ("Free",   5.00),
    "Pro":   ("Pro",   18.50),
    "Max5":  ("Max 5×", 92.50),
    "Max20": ("Max 20×",370.00),
}
DEFAULT_PLAN = "Pro"

# Sonnet 4.x pricing per million tokens
PRICE_INPUT          = 3.00
PRICE_OUTPUT         = 15.00
PRICE_CACHE_CREATION = 3.75
PRICE_CACHE_READ     = 0.30


# ---------- config ----------

def load_plan():
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            if data.get("plan") in PLANS:
                return data["plan"]
    except Exception:
        pass
    return DEFAULT_PLAN

def save_plan(plan):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"plan": plan}, f)
    except Exception:
        pass


# ---------- data ----------

def get_usage():
    now          = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=WINDOW_HOURS)
    totals       = dict(input=0, cache_creation=0, cache_read=0, output=0)
    oldest       = None

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
    cost = (
        totals["input"]          * PRICE_INPUT          +
        totals["output"]         * PRICE_OUTPUT         +
        totals["cache_creation"] * PRICE_CACHE_CREATION +
        totals["cache_read"]     * PRICE_CACHE_READ
    ) / 1_000_000

    return totals, cost, reset_at, now


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
        return "now  ✓"
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
BTN_ACT = "#1f6feb"   # active plan button bg
BTN_OFF = "#21262d"   # inactive plan button bg

F_TITLE = ("Consolas", 10, "bold")
F_ROW   = ("Consolas", 9)
F_BTN   = ("Consolas", 8, "bold")
F_FOOT  = ("Consolas", 8)

BAR_H = 6


def bar_color(pct):
    if pct < 60:  return GREEN
    if pct < 85:  return YELLOW
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
        self._plan   = load_plan()
        self._btns   = {}

        self._build_ui()

        self.bind("<ButtonPress-1>", self._drag_start)
        self.bind("<B1-Motion>",     self._drag_move)
        self.bind("<ButtonPress-3>", lambda e: self.destroy())

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
        row("Input",    self.v_input,  WHITE)
        row("Output",   self.v_output, GREEN)
        sep()
        row("Total 5h", self.v_total,  ACCENT)

        # Usage % + bar
        pf = tk.Frame(body, bg=BG)
        pf.pack(fill="x", pady=2)
        tk.Label(pf, text="Usage %", bg=BG, fg=DIM,
                 font=F_ROW, anchor="w", width=12).pack(side="left")
        tk.Label(pf, textvariable=self.v_pct, bg=BG,
                 fg=WHITE, font=F_ROW, anchor="e", width=9).pack(side="right")

        bar_outer = tk.Frame(body, bg=SEP, height=BAR_H + 2)
        bar_outer.pack(fill="x", pady=(1, 4))
        bar_outer.pack_propagate(False)
        self._bar_canvas = tk.Canvas(bar_outer, bg=SEP, height=BAR_H,
                                     highlightthickness=0)
        self._bar_canvas.pack(fill="x", padx=1, pady=1)

        sep()
        row("Reset in", self.v_reset, YELLOW)

        # Plan selector
        sep()
        plan_row = tk.Frame(body, bg=BG)
        plan_row.pack(fill="x", pady=3)
        for key in PLANS:
            label = PLANS[key][0]
            btn = tk.Label(plan_row, text=label, font=F_BTN, cursor="hand2",
                           padx=5, pady=2, relief="flat")
            btn.pack(side="left", padx=2)
            btn.bind("<Button-1>", lambda e, k=key: self._set_plan(k))
            self._btns[key] = btn
        self._update_btns()

        # Footer
        foot = tk.Frame(self, bg=BG, pady=2)
        foot.pack(fill="x")
        tk.Label(foot, textvariable=self.v_updated, bg=BG,
                 fg=FOOTER, font=F_FOOT, anchor="e").pack(fill="x", padx=10)

    def _update_btns(self):
        for key, btn in self._btns.items():
            active = (key == self._plan)
            btn.configure(
                bg=BTN_ACT if active else BTN_OFF,
                fg=WHITE   if active else DIM,
            )

    def _set_plan(self, plan):
        self._plan = plan
        save_plan(plan)
        self._update_btns()

    # ---- refresh ----

    def _refresh(self):
        totals, cost, reset_at, now = get_usage()
        total       = (totals["input"] + totals["cache_creation"]
                       + totals["cache_read"] + totals["output"])
        limit       = PLANS[self._plan][1]
        pct         = min(cost / limit * 100, 100) if limit else 0

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
        w = c.winfo_width() or 190
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
