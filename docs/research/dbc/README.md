# BMW N54 CAN Database References

This catalog highlights publicly accessible CAN database (DBC) files and signal
maps that document PT-CAN and KCAN traffic for BMW E8x/E9x chassis equipped with
the N54 running Siemens MSD80/81 DMEs.

## commaai/opendbc
- **Link:** https://github.com/commaai/opendbc
- **Scope:** Community-maintained DBC collection used by openpilot; includes the
  `dbc/bmw_e9x.dbc` definition derived from N54 and N55 owners logging PT-CAN on
  E9x chassis.
- **N54-relevant signals:** Engine speed (`0x316`), load/torque broadcasts
  (`0x329`), and DSC coordination frames (`0x399`) that surface boost control and
  traction-reduction states.

## timurrrr/dbc
- **Link:** https://github.com/timurrrr/dbc
- **Scope:** Personal repository aggregating BMW CAN research with a focus on
  E90/E92 N54 platforms.
- **N54-relevant files:** `bmw_e90_kcan.dbc` and supporting notes describing
  KCAN/KCAN2 layout captured during MSD80 flashing and datalogging sessions.

## Bimmerlabs N54 CAN captures
- **Link:** https://forum.bimmerlabs.com/t/n54-can-logging-database/112
- **Scope:** Forum thread cataloging CAN logs gathered while developing the
  Bimmerlabs flashing suite for MSD80 and MSD81 DMEs.
- **N54-relevant assets:** `kcan2_logs/335i_n54_msd81.dbc` and the accompanying
  PT-CAN spreadsheets that map message IDs to Siemens RAM addresses for logging.

## RFTX-TUNING/RFTX_SOFTWARE
- **Link:** https://github.com/RFTX-TUNING/RFTX_SOFTWARE
- **Scope:** Open-source tooling combining calibration editors with CAN reverse-
  engineering assets for MSD8x DMEs.
- **N54-relevant files:** `docs/can/ptcan_msd8x.xlsx` and `docs/can/kcan2_e9x.dbc`
  (if present) outlining torque, boost, and diagnostics frames observed on N54
  vehicles during flashing.

> **Tip:** Always confirm scaling factors directly in the referenced DBC or raw
> capture logs before integrating the data into flashing or logging tooling.
