"""Claude Code statusLine command: saves the session JSON for the LCD dashboard and prints a short status line."""
import json
import os
import sys

from claude_info import STATUS_PATH


def main():
    raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace")
    try:
        j = json.loads(raw)
    except ValueError:
        print("status: bad input")
        return
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(raw)
    os.replace(tmp, STATUS_PATH)  # atomic, so the dashboard never reads half a file

    model = (j.get("model") or {}).get("display_name", "?")
    ctx = (j.get("context_window") or {}).get("used_percentage")
    parts = [model, f"ctx {ctx:.0f}%" if isinstance(ctx, (int, float)) else "ctx --"]
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        p = ((j.get("rate_limits") or {}).get(key) or {}).get("used_percentage")
        if isinstance(p, (int, float)):
            parts.append(f"{label} {p:.0f}%")
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
