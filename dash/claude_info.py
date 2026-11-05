"""Claude Code session info for the LCD dashboard.

Sources, best first:
  1. status.json written by statusline.py (has rate limits + exact context size)
  2. newest transcript .jsonl under ~/.claude/projects (model + tokens only)
"""
from __future__ import annotations

import glob
import json
import os
import time

STATUS_PATH = os.path.join(os.environ.get("LOCALAPPDATA", "."), "TrofeoLCD", "claude_status.json")
PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")
STATUS_FRESH_S = 15 * 60  # statusline only runs on events, so allow a long gap

_cache = {"path": None, "mtime": 0.0, "data": None}


def _newest_transcript():
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))  # top level only: skips subagent logs
    return max(files, key=os.path.getmtime) if files else None


def parse_transcript(lines) -> dict | None:
    """Model + token totals from transcript lines. Usage repeats per content block, so dedupe by message id."""
    seen, out_total, last = set(), 0, None
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msg = d.get("message") or {}
        u = msg.get("usage")
        if d.get("type") != "assistant" or not u or d.get("isSidechain"):
            continue
        mid = msg.get("id") or d.get("uuid")
        if mid in seen:
            continue
        seen.add(mid)
        out_total += u.get("output_tokens", 0) or 0
        last = (msg, u, d)
    if last is None:
        return None
    msg, u, d = last
    ctx = sum((u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return {"model": msg.get("model", "?"), "effort": d.get("effort"), "context_tokens": ctx,
            "output_tokens": out_total, "context_size": None, "context_pct": None,
            "five_hour": None, "seven_day": None, "cost": None, "source": "transcript"}


def _from_status():
    try:
        if time.time() - os.path.getmtime(STATUS_PATH) > STATUS_FRESH_S:
            return None
        with open(STATUS_PATH, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return None
    cw = j.get("context_window") or {}
    rl = j.get("rate_limits") or {}
    return {"model": (j.get("model") or {}).get("display_name") or (j.get("model") or {}).get("id", "?"),
            "effort": None,
            "context_tokens": cw.get("total_input_tokens"),
            "output_tokens": cw.get("total_output_tokens"),
            "context_size": cw.get("context_window_size"),
            "context_pct": cw.get("used_percentage"),
            "five_hour": rl.get("five_hour"), "seven_day": rl.get("seven_day"),
            "cost": (j.get("cost") or {}).get("total_cost_usd"), "source": "statusline"}


def snapshot() -> dict | None:
    st = _from_status()
    path = _newest_transcript()
    tr = None
    if path:
        mt = os.path.getmtime(path)
        if (path, mt) != (_cache["path"], _cache["mtime"]):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    _cache.update(path=path, mtime=mt, data=parse_transcript(f))
            except OSError:
                pass
        tr = _cache["data"]
    if st and tr:
        st["output_tokens"] = tr["output_tokens"]  # session total beats last-response count
        st["effort"] = tr["effort"]
    return st or tr


if __name__ == "__main__":
    sample = [
        json.dumps({"type": "assistant", "effort": "high", "message": {"id": "a", "model": "m1", "usage": {"input_tokens": 1, "cache_read_input_tokens": 9, "output_tokens": 5}}}),
        json.dumps({"type": "assistant", "message": {"id": "a", "model": "m1", "usage": {"input_tokens": 1, "cache_read_input_tokens": 9, "output_tokens": 5}}}),
        json.dumps({"type": "assistant", "message": {"id": "b", "model": "m2", "usage": {"input_tokens": 2, "cache_creation_input_tokens": 3, "output_tokens": 7}}}),
        json.dumps({"type": "assistant", "isSidechain": True, "message": {"id": "c", "model": "x", "usage": {"output_tokens": 100}}}),
        "not json",
    ]
    r = parse_transcript(sample)
    assert r["model"] == "m2" and r["context_tokens"] == 5 and r["output_tokens"] == 12, r
    print("self-test ok;", snapshot())
