# Claude Code Usage HUD

A lightweight floating desktop widget that shows your **Claude Code token usage** and **session reset timer** in real time. Built for the Claude.ai Standard Plan.

![HUD Preview](preview.png)

---

## What it shows

| Field | Description |
|---|---|
| Input | Input tokens used in the last 5 hours |
| Output | Output tokens used in the last 5 hours |
| Total 5h | Combined token sum for the current window |
| Usage % | Estimated % of your session limit (progress bar) |
| Reset in | Countdown until the 5-hour usage window resets |

The progress bar turns **yellow** above 60% and **red** above 85%.

---

## Requirements

- Windows 10 / 11
- [Python 3.8+](https://www.python.org/downloads/) — must be added to PATH during install
- [Claude Code](https://claude.ai/code) installed and used at least once

No extra Python packages needed — only the standard library.

---

## Installation

1. Download or clone this repo
2. Place the folder anywhere you like (e.g. `Desktop\Claude_HUD`)
3. Double-click **`start_hud.bat`** to launch

The window appears in the top-right corner of your screen.  
**Drag** it anywhere. **Right-click** to close.

---

## Auto-start with Windows

To launch the HUD automatically when Windows starts:

1. Press `Win + R`, type `shell:startup`, press Enter
2. Right-click `start_hud.bat` → **Create shortcut**
3. Move that shortcut into the Startup folder

---

## Configuration

Open `claude_hud.py` in any text editor and adjust the top constants:

```python
WINDOW_HOURS = 5        # Claude Code's rolling usage window (don't change)
REFRESH_MS   = 15_000   # How often to refresh, in milliseconds
OUTPUT_LIMIT = 2_000_000  # Your plan's approx output token limit per window
                          # Pro ≈ 1_000_000 / Max 5x ≈ 5_000_000
```

Tune `OUTPUT_LIMIT` to match your plan so the % bar is accurate.

---

## How it works

Claude Code stores every conversation as `.jsonl` files in `~/.claude/projects/`.  
The HUD reads those files, sums up token usage from the last 5 hours, and calculates when the oldest message in the window expires — that's the reset time.

No API calls. No internet connection. Fully local.

---

## Files

| File | Purpose |
|---|---|
| `claude_hud.py` | Main script |
| `start_hud.bat` | Launch without a console window |
| `stop_hud.bat` | Kill the HUD |

---

## License

MIT — do whatever you want with it.
