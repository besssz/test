# Siemens MSD80/81 Checksum References (BMW N54)

Open-source checksum material for the Siemens MSD80/81 DMEs is critical when
editing N54 calibrations. The resources below describe the additive and CRC
verification steps required to validate binaries prior to flashing.

## bri3d/MSD80-tools
- **Link:** https://github.com/bri3d/MSD80-tools
- **License:** GPL-3.0.
- **Summary:** Toolkit assembled during the Bimmerlabs N54 research effort. The
  `msd80/checksum.py` and `msd81/checksum.py` modules implement block-sum and
  CRC16/CRC32 verification routines for IJE0S/I8A0S ROM families, including the
  calibration footer words at `0x1F4000`.
- **Usage notes:** Scripts can run standalone to validate CAL-only edits or be
  embedded into custom flashers. They document how VIN patches require updating
  the additive checksum word in the calibration footer.

## Bimmerlabs checksum notes (forum release)
- **Link:** https://forum.bimmerlabs.com/t/open-source-n54-flashing-suite/87
- **Summary:** Archive includes PDF/Markdown notes that break down the MSD80/81
  checksum flow. Provides context on when to recompute the additive sum vs. full
  CRC-32 depending on whether CODE or CAL segments changed.
- **Usage notes:** Often referenced alongside the Bimmerlabs Python flashers to
  validate stage maps before OBD programming.

## e90post MSD80 checksum thread
- **Link:** https://www.e90post.com/forums/showthread.php?t=1517554
- **License:** Forum posts shared for research/educational use; obtain permission
  before redistributing snippets.
- **Summary:** Community-maintained thread capturing disassembled checksum
  subroutines for MSD80/81 DMEs. Contributors mapped per-segment additive checks
  and the footer CRC-32 calculation, highlighting pitfalls when performing CAL-
  only flashes.
- **Usage notes:** Includes validation scripts and IDA annotations aligned with
  stock IJE0S/I8A0S binaries.

## RFTX-TUNING/RFTX_SOFTWARE checksum library
- **Link:** https://github.com/RFTX-TUNING/RFTX_SOFTWARE
- **License:** GPL-3.0 (confirm per project subdirectory).
- **Summary:** The `src/RFTX.BMW.DME/Checksum/` modules provide C# and Python
  implementations of Siemens MSD8x block checksums. Source comments document
  calibration segment offsets for N54 calibrations and show how to batch-verify
  patched bins during automated flashing.
- **Usage notes:** Designed for integration with the repository’s MSD80/81
  console flashers but portable to Python-only workflows.

> **Implementation tip:** MSD80/81 full flashes typically recompute both the
> additive CAL checksum and the footer CRC-32. CAL-only flashes often require
> updating just the final 16-bit additive word as long as CODE and BOOT segments
> remain untouched.
