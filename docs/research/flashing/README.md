# BMW N54 DME Flashing & Diagnostics Workflows

The focus of this catalog is the Siemens MSD80/81 DMEs powering the BMW N54.
Highlighted resources document flashing pipelines, security access helpers, and
diagnostic utilities that apply directly to the E8x/E9x N54 platforms when
paired with a wired USB K+DCAN-style interface. WiFi-only tooling is out of
scope for this summary.

## CAFlash (reference implementation)
- **Link:** https://www.caflash.co.uk/
- **Scope:** Commercial Android application that popularized fast N54 flashing
  workflows over K+DCAN and MHD/Thor WiFi adapters.
- **Key behaviours to emulate:**
  - Dedicated *Identify*, *Flash*, *Logging*, *Codes*, and *Readiness* tabs so
    drivers can stage tunes, monitor the engine, and clear faults without
    switching tools.
  - Flash presets that prompt for hardware and fuel configuration (TMAP, coil
    kits, ethanol range) before writing the calibration.
  - Full flash timing around seven minutes and calibration-only updates close to
    one minute when using high-quality USB cables.
- **Hardware expectations:** BimmerGeeks or equivalent K+DCAN USB cable, stable
  13.5 V supply, and optionally a bench harness for recovery flashing.

The open-source projects below provide reusable components for replicating the
CAFlash feature set on the N54 while remaining fully USB-centric.

## CAFDumps/BMWFlash fork for MSD80
- **Link:** https://github.com/binary-modder/BMWFlash
- **License:** GPL-3.0.
- **Summary:** Windows-based C# utility capable of reading, writing, and erasing
  Siemens MSD80 and MSD81 DMEs over KWP2000. Supports full and partial flashes,
  VIN coding, and checksum recalculation via plugin DLLs. Remains a valuable
  reference for replicating CAFlash-style workflows on open platforms.
- **Workflow highlights:** Uses a custom bootloader injected through the OBD-II
  port, then leverages block-based flashing with verification. Includes INPA
  scripts and configuration files for logging key states during programming.
- **Required hardware:** K+DCAN USB cable or equivalent DCAN interface. Optional
  bench harness for out-of-vehicle flashing.

## Bimmerlabs N54 programming suite
- **Link:** https://forum.bimmerlabs.com/t/open-source-n54-flashing-suite/87
- **License:** Mixed; released for research with permissive terms.
- **Summary:** Archive containing Python and .NET tools for MSD80/81. Provides
  bootloader unlock scripts, seed/key helpers, and checksum validators that feed
  into the Bimmerlabs OTS map workflow.
- **Workflow highlights:** Combines ENET/K+DCAN transport adapters with ISO-TP
  scripts to enter programming session 0x13, upload a RAM-resident kernel, and
  stream calibration segments from disk. Bundled documentation covers recovery
  procedures if flashing is interrupted.
- **Required hardware:** K+DCAN cable, bench power supply capable of sustaining
  13.5 V during write operations, and optional CAN analyzer for monitoring
  PT-CAN traffic.

## MSD80 bench flashing scripts (github.com/bri3d/MSD80-tools)
- **Link:** https://github.com/bri3d/MSD80-tools
- **License:** GPL-3.0.
- **Summary:** Collection of Python utilities that automate seed/key access,
  checksum generation, and block programming for MSD80/81 DMEs. Often paired with
  Bimmerlabs calibration packages.
- **Workflow highlights:** `msd80_flash.py` sequences the unlock handshake,
  transitions the ECU into programming mode, and writes calibration or full flash
  images while logging PT-CAN status frames.
- **Required hardware:** Configurable for K+DCAN or USB-to-CAN adapters (ValueCAN,
  PCAN) using python-can backends.

## RFTX-TUNING/RFTX_SOFTWARE flashing suite
- **Link:** https://github.com/RFTX-TUNING/RFTX_SOFTWARE
- **License:** GPL-3.0 (verify component-level notices).
- **Summary:** Multi-language toolkit bundling calibration editors, checksum
  libraries, and automated flashing pipelines for Siemens MSD80/81. The
  `tools/RFTX.BMW.DME.Console` application orchestrates KWP2000 sessions while
  invoking shared checksum/seed-key helpers.
- **Workflow highlights:** Provides scripted routines for reading, unlocking,
  flashing, and verifying DMEs. Sample configs illustrate OBD-based sessions with
  USB CAN adapters and bench-mode flashing with SocketCAN devices. Includes
  recovery instructions leveraging custom bootloaders shipped in `kernels/`.
- **Required hardware:** Supports K+DCAN and USB-to-CAN/FD devices. Bench harness
  pinouts and PSU requirements are documented under `docs/harness/`.

> **Tip:** Maintain a stable power supply and log PT-CAN traffic during flashes.
> MSD80/81 DMEs enter transport protection if voltage sags below 12 V or if the
> seed/key exchange fails three times in a row.

## Hardware compatibility notes

`tools/n54flash.py` can talk to hardware in three ways:

1. `--iface slcan` – USB K+DCAN and other Lawicel-style adapters exposed as
   serial devices.
2. `--iface pcan` – PEAK PCAN-USB adapters via the python-can back end.
3. `--iface bavtech` – Bavarian Technic diagnostic cables by loading the vendor
   J2534 DLL (Windows only) and streaming raw CAN frames through it.

The Bavarian Technic interface still requires the official driver package, but
no longer needs to masquerade as a generic slcan/PCAN device; provide the DLL
path via `--bt-dll` (or set `BAVTECH_DLL=C:\\Path\\To\\btj2534.dll`) and the
flasher will drive the J2534 API directly.

```bash
python tools/n54flash.py \
    --iface bavtech \
    --bt-dll "C:\\Program Files\\Bavarian Technic\\btj2534.dll" \
    --info
```
