# BMW N54 Calibration Definition & Binary Archives

This index tracks open-source projects that collect definition files (XDF) and
stock/tuned binaries for the Siemens MSD80/81 DMEs used with the BMW N54. Each
entry notes where calibration definitions live, which ROM variants are covered,
and any supplemental tooling that assists with custom tunes.

## dmacpro91/BMW-XDFs
- **Link:** https://github.com/dmacpro91/BMW-XDFs
- **Focus:** Community-maintained XDF definitions for the legacy TunerPro
  workflow targeting N54 and early N55 ROMs.
- **Notable assets:**
  - `XDF/N54/` directory organized by ROM ID (e.g., `IJE0S`, `I8A0S`, `INA0S`)
    with per-table descriptions and axis metadata.
  - `Tables/` CSV exports summarizing load, boost, timing, and fueling tables to
    assist in cross-referencing axis scaling between ROM revisions.
- **Extras:** Includes patch templates for common hardware conversions (3.5 bar
  TMAP, upgraded LPFP) plus checksum helper notes referencing MSD80 additive
  correction words.
- **License:** Refer to the repository’s LICENSE file; derivative tables often
  inherit community permissive terms.

## Corbanistan/BMW-N54-Tuning-Resources
- **Link:** https://github.com/Corbanistan/BMW-N54-Tuning-Resources
- **Focus:** Aggregated binaries, map packs, and documentation specific to N54
  custom tuning efforts.
- **Notable assets:**
  - `bins/` archive containing stock dumps (e.g., `IJE0S`, `I8A0S`, `IJEOS`) and
    community stage files for comparison against factory calibrations.
  - `xdf/` folder mirroring TunerPro definitions aligned with the bins and
    annotated with table comments explaining boost control, torque targeting, and
    safety limiters.
  - `docs/` references covering map definitions, logging parameter cheat sheets,
    and guidelines for building base tunes.
- **Extras:** Includes scripts for splitting/merging CAL segments and checksum
  calculators tailored to MSD80 16-bit summing. Some branches also track
  user-contributed flex-fuel experiments for future integration.
- **License:** Repository README clarifies redistribution terms for shared bins;
  confirm before packaging into commercial workflows.

> **Tip:** Pair these XDFs with the flashing utilities documented under
> `docs/research/flashing/` and checksum helpers in `docs/research/checksums/`
> when assembling N54-specific calibration workflows.
