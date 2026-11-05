"""TrofeoLCD.exe — one file to share: installs itself on first run, then mirrors a Windows
extended display to the Thermalright Trofeo Vision 9.16 LCD and shows the RAM/Claude dashboard on it.

  TrofeoLCD.exe              first run: install (UAC); afterwards: run
  TrofeoLCD.exe --run        run mirror + dashboard (the logon task uses this)
  TrofeoLCD.exe --uninstall  remove task, virtual display and install folder
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import winreg

APP = "TrofeoLCD"
INSTALL_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), APP)
EXE = os.path.join(INSTALL_DIR, APP + ".exe")
TASK = "TrofeoLCDMirror"
RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VDD = os.path.join(RES, "vdd")
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)
CFG = os.path.join(DATA_DIR, "app.json")
TRCC_PROCS = {"trcc.exe", "usblcd.exe", "usblcdnew.exe"}
NO_WINDOW = 0x08000000


def log(text):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "app.log"), "a", encoding="utf-8") as f:
            f.write(f"{__import__('time').strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {text}\n")
    except OSError:
        pass


def msg(text, error=False):
    log(("ERROR: " if error else "MSG: ") + text.replace("\n", " | "))
    ctypes.windll.user32.MessageBoxW(0, text, APP, 0x10 if error else 0x40)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_admin(arg):
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, arg, None, 1)
    log(f"relaunch_admin {arg} -> {r}")
    return r > 32


def run_quiet(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, creationflags=NO_WINDOW)


def kill(names, keep=()):
    import psutil
    victims = []
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() in names and p.pid not in keep:
            try:
                p.kill()
                victims.append(p)
            except psutil.Error:
                pass
    psutil.wait_procs(victims, timeout=10)  # files stay locked until the process is really gone


def kill_other_copies():
    import psutil
    me = psutil.Process()
    keep = {me.pid} | {p.pid for p in me.parents()}  # onefile = bootloader parent + child
    kill({APP.lower() + ".exe"}, keep)


def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"dashboard": True}


SHORTCUTS = [os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs", APP + ".lnk"),
             os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop", APP + ".lnk")]


def make_shortcuts():
    for lnk in SHORTCUTS:
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{EXE}';$s.Arguments='--settings';$s.WorkingDirectory='{INSTALL_DIR}';$s.Save()")
        run_quiet(["powershell", "-NoProfile", "-Command", ps])


def app_running():
    h = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "Local\\TrofeoLCDApp")  # SYNCHRONIZE
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return ctypes.windll.kernel32.GetLastError() == 5  # exists but owned by the elevated copy


def settings():
    if not app_running():
        subprocess.Popen([EXE if os.path.exists(EXE) else sys.executable, "--run"], creationflags=NO_WINDOW)
    import settings_ui
    settings_ui.main()


def set_monitor_modes():
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\WUDF\Services\usbmmIdd\Parameters\Monitors"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "1920,462")
        for name, val in (("0", "1920,462"), ("1", "1920,480"), ("2", "1920,1080")):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)


def install():
    log("install: begin")
    kill_other_copies()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    if os.path.normcase(sys.executable) != os.path.normcase(EXE):
        for attempt in range(10):  # antivirus may still hold the old exe for a moment
            try:
                shutil.copy2(sys.executable, EXE)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                __import__("time").sleep(1)
    for name in ("License.txt",):  # Amyuni license must travel with the driver
        shutil.copy2(os.path.join(VDD, name), os.path.join(INSTALL_DIR, "usbmmidd-" + name))
    # each "install" adds another device node, so only install the driver once per PC
    present = "USB Mobile Monitor" in run_quiet(["pnputil", "/enum-devices", "/class", "Display"]).stdout
    r = run_quiet(["cmd", "/c", "echo", "driver already installed"]) if present else \
        run_quiet([os.path.join(VDD, "deviceinstaller64.exe"), "install", "usbmmIdd.inf", "usbmmidd"], cwd=VDD)
    set_monitor_modes()
    t = run_quiet(["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "ONLOGON", "/RL", "HIGHEST",
                   "/TR", f'"{EXE}" --run'])
    if t.returncode != 0:
        msg(f"Could not create the logon task:\n{t.stderr or t.stdout}", error=True)
    run_quiet(["schtasks", "/Change", "/TN", "TRCCAppStartup", "/DISABLE"])  # TRCC would grab the screen
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CFG):
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump({"dashboard": True}, f, indent=2)
    make_shortcuts()
    msg("Installed. The LCD now works as an extra monitor and starts with Windows.\n"
        "Settings: the TrofeoLCD shortcut on the desktop / Start menu.\n\n"
        f"Driver installer said:\n{(r.stdout or r.stderr).strip()[:300]}\n\n"
        f"Uninstall: {EXE} --uninstall")
    subprocess.Popen([EXE, "--run"], creationflags=NO_WINDOW)
    import settings_ui
    settings_ui.main()


def uninstall():
    kill_other_copies()
    run_quiet(["schtasks", "/Delete", "/F", "/TN", TASK])
    run_quiet(["schtasks", "/Change", "/TN", "TRCCAppStartup", "/ENABLE"])
    for lnk in SHORTCUTS:
        if os.path.exists(lnk):
            os.remove(lnk)
    di = os.path.join(VDD, "deviceinstaller64.exe")
    for args in (["enableidd", "0"], ["stop", "usbmmidd"], ["remove", "usbmmidd"]):
        run_quiet([di, *args], cwd=VDD)
    # the running exe may live in INSTALL_DIR, so delete it after we exit
    subprocess.Popen(f'cmd /c timeout /t 3 >nul & rmdir /s /q "{INSTALL_DIR}"', shell=True,
                     creationflags=NO_WINDOW)
    msg("TrofeoLCD removed. You can start TRCC again.")


def run():
    if not is_admin() and relaunch_admin("--run"):
        return  # the elevated copy takes over (needed to switch the virtual display on)
    if ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\TrofeoLCDApp") and \
            ctypes.windll.kernel32.GetLastError() == 183:
        return  # already running
    kill(TRCC_PROCS)
    import extended_display
    mirror = threading.Thread(target=extended_display.main, daemon=True)
    mirror.start()
    if not load_cfg().get("dashboard", True):
        mirror.join()
        return
    import tkinter as tk
    import lcd_dashboard
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    mon = None
    while mon is None:  # the virtual display may take a few seconds to appear
        mon = lcd_dashboard.find_panel()
        if mon is None:
            mirror.join(3)
    root = tk.Tk()
    lcd_dashboard.Dashboard(root, mon)
    root.mainloop()
    mirror.join()  # Esc closes the dashboard; the mirror keeps the LCD running


def selftest():
    """No-install diagnostics: writes what works to DATA_DIR/selftest.txt."""
    out = [f"exe={sys.executable}", f"admin={is_admin()}", f"res={RES}", f"vdd={os.listdir(VDD)}"]
    for name, check in (
        ("libusb", lambda: __import__("trofeo").get_backend()),
        ("device", lambda: __import__("trofeo").find_device()),
        ("display", lambda: __import__("lcd_dashboard").find_panel()),
        ("claude", lambda: __import__("claude_info").snapshot()),
        ("tk", lambda: __import__("tkinter").TkVersion),
        ("video", lambda: (lambda m, c: (c["media"]["path"], m.cv2.VideoCapture(c["media"]["path"]).read()[0]))(
            __import__("media"), __import__("lcd_dashboard").load_custom())),
        ("hw", lambda: (__import__("hw_info").snapshot(), __import__("time").sleep(6),
                        __import__("hw_info").snapshot())[2]),
    ):
        try:
            out.append(f"{name}: OK {check()!r}"[:300])
        except BaseException as e:  # SystemExit from trofeo counts as a failure here
            out.append(f"{name}: FAIL {type(e).__name__}: {e}")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    log(f"start arg={arg!r} admin={is_admin()} exe={sys.executable}")
    if arg == "--selftest":
        return selftest()
    if arg == "--run":
        return run()
    if arg == "--settings":
        return settings()
    if arg in ("--install", "--uninstall"):
        if not is_admin():
            if not relaunch_admin(arg):
                msg("Administrator rights are needed.", error=True)
            return
        return install() if arg == "--install" else uninstall()
    installed = os.path.exists(EXE) and os.path.normcase(sys.executable) == os.path.normcase(EXE)
    if installed:
        return settings()
    if is_admin():
        install()
    elif not relaunch_admin("--install"):
        msg("Administrator rights are needed to install.", error=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:  # windowed exe has no console: show the error instead of vanishing
        import traceback
        log(traceback.format_exc())
        msg(f"{type(e).__name__}: {e}", error=True)
        sys.exit(1)  # our message box is enough; re-raising adds PyInstaller's second dialog
