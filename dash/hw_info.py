"""HWMonitor-style sensor readout via LibreHardwareMonitorLib (bundled in vendor/lhm).

Needs admin for CPU temperatures (the app runs elevated). A background thread refreshes a
snapshot so the Tk thread never waits on slow sensors (disks, SuperIO).
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import paths  # noqa: E402

REFRESH_S = 2.0
_snap: list = []
_err: str | None = None
_started = False


def _pick(sensors, stype, names=None):
    """First sensor of a type, preferring the given names in order."""
    cands = [s for s in sensors if str(s.SensorType) == stype and s.Value is not None]
    for n in names or ():
        for s in cands:
            if s.Name == n:
                return s
    return cands[0] if cands and not names else None


def summarize(hw_type: str, name: str, sensors) -> list[tuple[str, str, float | None]]:
    """[(label, text, bar_pct)] for one device; empty list = skip the device."""
    rows = []

    def add(label, s, fmt, pct=None):
        if s is not None:
            rows.append((label, fmt.format(s.Value), pct))

    if hw_type == "Cpu":
        load = _pick(sensors, "Load", ["CPU Total"])
        add("Load", load, "{:.0f}%", load.Value if load else None)
        add("Temperature", _pick(sensors, "Temperature", ["Core (Tctl/Tdie)", "CPU Package", "Core Average", "Core (Tctl)"]), "{:.0f}°C")
        clocks = [s for s in sensors if str(s.SensorType) == "Clock" and s.Value and "Core" in s.Name]
        if clocks:
            rows.append(("Clock", f"{max(c.Value for c in clocks) / 1000:.2f} GHz", None))
        add("Power", _pick(sensors, "Power", ["Package", "CPU Package"]), "{:.0f} W")
    elif hw_type.startswith("Gpu"):
        load = _pick(sensors, "Load", ["GPU Core"])
        add("Load", load, "{:.0f}%", load.Value if load else None)
        add("Temperature", _pick(sensors, "Temperature", ["GPU Core"]), "{:.0f}°C")
        add("Hot Spot", _pick(sensors, "Temperature", ["GPU Hot Spot"]), "{:.0f}°C")
        used = _pick(sensors, "SmallData", ["GPU Memory Used", "D3D Dedicated Memory Used"])
        total = _pick(sensors, "SmallData", ["GPU Memory Total"])
        if used is not None:
            pct = used.Value / total.Value * 100 if total and total.Value else None
            tail = f" / {total.Value / 1024:.0f} GB" if total and total.Value else " GB"
            rows.append(("VRAM", f"{used.Value / 1024:.1f}{tail}", pct))
        add("Clock", _pick(sensors, "Clock", ["GPU Core"]), "{:.0f} MHz")
        add("Power", _pick(sensors, "Power", ["GPU Package", "GPU Power", "GPU Core"]), "{:.0f} W")
        add("Fan", _pick(sensors, "Fan", ["GPU Fan"]), "{:.0f} RPM")
    elif hw_type == "Storage":
        add("Temperature", _pick(sensors, "Temperature", ["Temperature", "Composite Temperature"]), "{:.0f}°C")
    elif hw_type in ("Motherboard", "SuperIO"):
        for s in sensors:
            if str(s.SensorType) == "Fan" and s.Value and s.Value > 0:
                rows.append((s.Name, f"{s.Value:.0f} RPM", None))
    return rows


def _walk(hw):
    hw.Update()
    yield hw
    for sub in hw.SubHardware:  # SuperIO fans live under the motherboard
        yield from _walk(sub)


def _loop():
    global _snap, _err
    try:
        import clr
        clr.AddReference(paths.lhm_dll())
        from LibreHardwareMonitor.Hardware import Computer
        c = Computer()
        c.IsCpuEnabled = c.IsGpuEnabled = c.IsStorageEnabled = c.IsMotherboardEnabled = True
        c.Open()
    except Exception as e:
        _err = f"LHM: {e}"
        return
    while True:
        snap = []
        for hw in c.Hardware:
            try:
                for h in _walk(hw):
                    rows = summarize(str(h.HardwareType), h.Name, list(h.Sensors))
                    if rows:
                        snap.append((h.Name, rows))
            except Exception:
                continue
        _snap = snap
        time.sleep(REFRESH_S)


def snapshot():
    """(devices, error): devices = [(name, [(label, text, pct)])]."""
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True).start()
    return _snap, _err


if __name__ == "__main__":
    class S:  # tiny sensor stub for the self-test
        def __init__(self, t, n, v):
            self.SensorType, self.Name, self.Value = t, n, v
    rows = summarize("Cpu", "x", [S("Load", "CPU Total", 12.0), S("Temperature", "Core (Tctl/Tdie)", 41.0),
                                  S("Clock", "Core #1", 4500.0), S("Power", "Package", 55.0)])
    assert rows[0] == ("Load", "12%", 12.0) and rows[1][1] == "41°C" and rows[2][1] == "4.50 GHz", rows
    snapshot()
    time.sleep(6)
    devs, err = snapshot()
    print("err:", err)
    for name, r in devs:
        print(name, r)
