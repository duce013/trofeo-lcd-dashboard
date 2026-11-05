# Third-party notices

This project includes or depends on the components below. Each keeps its own license; they are **not** covered by this project's MIT license.

---

## 1. Amyuni usbmmidd (virtual display driver) — `vdd/`

Copyright 2014-2021 Amyuni Technologies Inc. — https://www.amyuni.com

Full license: `vdd/License.txt` (also installed as `usbmmidd-License.txt`). Key terms:

> Permission is granted to anyone to use this software for any purpose subject to
> the following restrictions:
> 1. The origin of this software must not be misrepresented; you must not claim
>    that you wrote the original software. If you use this software in a product,
>    an acknowledgment in the product documentation would be required.
> 2. Altered versions must be plainly marked as such, and must not be
>    misrepresented as being the original software.
> 3. This notice may not be removed or altered from any distribution.

The driver files are redistributed **unmodified**. Thanks to Amyuni Technologies. The free version may show an advertisement page; a commercial version without it is available from Amyuni.

---

## 2. LibreHardwareMonitor (sensors) — `vendor/lhm/`

`LibreHardwareMonitorLib.dll` and its dependencies — https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
License: **Mozilla Public License 2.0** — https://www.mozilla.org/en-US/MPL/2.0/

Redistributed unmodified; source code is available from the repository above.

---

## 3. Python packages (bundled into `TrofeoLCD.exe`)

| Package | License |
|---|---|
| pyusb | BSD-3-Clause |
| libusb-package (ships libusb-1.0.dll) | MIT (package), LGPL-2.1 (libusb) |
| mss | MIT |
| psutil | BSD-3-Clause |
| pythonnet | MIT |
| Pillow | MIT-CMU (HPND) |
| opencv-python-headless | Apache-2.0 (bundles FFmpeg, LGPL-2.1) |
| customtkinter | MIT |
| PyInstaller (build tool, bootloader) | GPL-2.0 with bootloader exception |

---

## 4. Upstream project and references

- [Tanqor/thermalright-trofeo-lcd](https://github.com/Tanqor/thermalright-trofeo-lcd) — MIT. This project started as a copy of it; the screen-link code in `src/` is derived from it (changes: portrait rotation, single-instance guard, bundled libusb, smoother change detection, installer).
- USB protocol cross-checked against [Lexonight1/thermalright-trcc-linux](https://github.com/Lexonight1/thermalright-trcc-linux).
