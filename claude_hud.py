"""
Claude Code Usage HUD
Floating always-on-top window showing token usage, % of session limit, and reset time.
Right-click for menu (calibrate, refresh, close). Drag to move. Click plan to switch.
"""

import tkinter as tk
import tkinter.simpledialog as simpledialog
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

# Default output-token limits per 5h window.
# These can be overridden per plan via right-click → Calibrate.
PLANS = {
    "Free":  ("Free",      25_000),
    "Pro":   ("Pro",      247_000),
    "Max5":  ("Max 5×", 1_235_000),
    "Max20": ("Max 20×",4_940_000),
}
DEFAULT_PLAN = "Pro"


# ---------- config ----------

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_plan(cfg):
    p = cfg.get("plan", DEFAULT_PLAN)
    return p if p in PLANS else DEFAULT_PLAN

def load_custom_limit(cfg, plan):
    return cfg.get("custom_limits", {}).get(plan)

def save_custom_limit(plan, limit):
    cfg = load_config()
    cfg.setdefault("custom_limits", {})[plan] = limit
    save_config(cfg)

def save_plan_to_config(plan):
    cfg = load_config()
    cfg["plan"] = plan
    save_config(cfg)


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
BTN_ACT = "#1f6feb"
BTN_OFF = "#21262d"
MENU_BG = "#161b22"
MENU_FG = "#e6edf3"

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
        self._cfg    = load_config()
        self._plan   = load_plan(self._cfg)
        self._btns   = {}
        self._last_output = 0   # for calibration

        self._build_ui()

        self.bind("<ButtonPress-1>",   self._drag_start)
        self.bind("<B1-Motion>",       self._drag_move)
        self.bind("<ButtonPress-3>",   self._show_menu)
        self.bind("<Double-Button-1>", lambda e: self._force_refresh())

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"+{sw - 240}+20")

        self.after(0, self._refresh)

    # ---- layout ----

    def _build_ui(self):
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
        save_plan_to_config(plan)
        self._update_btns()

    # ---- right-click menu ----

    def _show_menu(self, event):
        menu = tk.Menu(self, tearoff=0,
                       bg=MENU_BG, fg=MENU_FG,
                       activebackground=BTN_ACT, activeforeground=WHITE,
                       borderwidth=1, relief="flat")
        menu.add_command(label="Force Refresh",  command=self._force_refresh)
        menu.add_command(label="Calibrate %…",   command=self._calibrate)
        menu.add_separator()
        menu.add_command(label="Close",          command=self.destroy)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _calibrate(self):
        """Ask user for the official % and compute the correct output-token limit."""
        if self._last_output == 0:
            simpledialog.messagebox.showwarning(
                "No data", "No output tokens found yet. Use Claude first.",
                parent=self)
            return

        official = simpledialog.askinteger(
            "Calibrate to official %",
            f"HUD reads {fmt_tokens(self._last_output)} output tokens.\n\n"
            f"What % does claude.ai → Settings → Usage show right now?",
            parent=self, minvalue=1, maxvalue=100)

        if not official:
            return

        new_limit = int(self._last_output / (official / 100))
        save_custom_limit(self._plan, new_limit)
        self._cfg = load_config()
        self._force_refresh()

    # ---- refresh ----

    def _get_limit(self):
        custom = load_custom_limit(self._cfg, self._plan)
        return custom if custom else PLANS[self._plan][1]

    def _force_refresh(self):
        if hasattr(self, "_timer"):
            self.after_cancel(self._timer)
        self._refresh()

    def _refresh(self):
        try:
            totals, reset_at, now = get_usage()
        except Exception:
            totals   = dict(input=0, cache_creation=0, cache_read=0, output=0)
            reset_at = None
            now      = datetime.now(timezone.utc)

        self._last_output = totals["output"]
        total = (totals["input"] + totals["cache_creation"]
                 + totals["cache_read"] + totals["output"])
        limit = self._get_limit()
        pct   = min(totals["output"] / limit * 100, 100) if limit else 0

        self.v_input.set(fmt_tokens(totals["input"]) if totals["input"] else "—")
        self.v_output.set(fmt_tokens(totals["output"]) if totals["output"] else "—")
        self.v_total.set(fmt_tokens(total) if total else "—")
        self.v_pct.set(f"{pct:.1f}%" if total else "—")
        self.v_reset.set(fmt_countdown(reset_at, now))
        self.v_updated.set(f"updated {now.strftime('%H:%M:%S')} UTC")

        self._draw_bar(pct)
        self._timer = self.after(REFRESH_MS, self._refresh)

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
