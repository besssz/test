# Siemens MSD80/81 Seed/Key Implementations (BMW N54)

Security access for the Siemens MSD80/81 DMEs follows the KWP2000 0x27 seed/key
handshake. The projects below document open implementations relied upon when
unlocking BMW N54 ECUs for flashing or diagnostics.

## bri3d/MSD80-tools seedkey helpers
- **Link:** https://github.com/bri3d/MSD80-tools/tree/master/seedkey
- **License:** GPL-3.0.
- **Summary:** Python helpers implementing the MSD80/81 Level 1 and Level 5
  security algorithms used by the Bimmerlabs team. Modules expose the XOR and
  rotation constants required to calculate keys from 16-bit seeds captured during
  OBD programming.
- **Usage notes:** Validated on both MSD80 (IJE0S) and MSD81 (I8A0S) ROMs using
  K+DCAN transports with python-can or INPA/Ediabas backends.

## Bimmerlabs forum release
- **Link:** https://forum.bimmerlabs.com/t/open-source-n54-flashing-suite/87
- **Summary:** Bundled documentation includes a walkthrough of the MSD80/81
  security handshake and examples of issuing 0x27 requests inside the open-source
  flashing scripts.
- **Usage notes:** Often paired with the checksum notes from the same drop to
  construct end-to-end N54 flashing workflows.

## e90post MSD80 seed/key thread
- **Link:** https://www.e90post.com/forums/showthread.php?t=1471938
- **License:** Forum-contributed scripts typically shared for educational use;
  confirm redistribution terms with the authors.
- **Summary:** Thread collecting IDA exports and C#/Python utilities for deriving
  MSD80 Level 5 keys. Contributors outline the substitution tables extracted from
  Siemens firmware and supply compiled DLLs used by legacy BMWFlash builds.
- **Usage notes:** Scripts expect hexadecimal seed input as logged from INPA or
  BMWFlash sessions and return the unlock key for programming services.

## RFTX-TUNING/RFTX_SOFTWARE security access
- **Link:** https://github.com/RFTX-TUNING/RFTX_SOFTWARE
- **License:** GPL-3.0 (confirm per component).
- **Summary:** `src/RFTX.BMW.DME/SecurityAccess/` hosts reusable MSD80/81 seed/key
  solvers with clear documentation of the XOR constants, rotation schedule, and
  message framing required for KWP2000 0x27 unlocks.
- **Usage notes:** Designed to pair with the project’s K+DCAN transport wrappers
  and console flashers but can be adapted into standalone Python tooling.

> **Tip:** Always log the ECU’s response codes when brute-forcing MSD80/81 keys;
> repeated failed attempts can trigger security timers that delay subsequent
> programming requests.
