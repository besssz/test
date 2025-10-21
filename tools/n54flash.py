"""BMW N54/MSD80 flashing helper.

This module provides a python-can based application that targets Siemens
MSD80/81 control units using the KWP2000 service set BMW deployed on the PT-CAN
bus. The command line interface is shaped after the CAFlash user experience but
focused exclusively on wired USB adapters:

* ``--info`` – enter the programming session and print the ECU identity.
* ``--backup FILE`` – dump the complete 1 MiB image to ``FILE``.
* ``--flash FILE`` – program the supplied 1 MiB image.
* ``--vin VIN17`` – optionally patch the VIN before flashing.
* Hardware profile switches (``--tmap``, ``--ethanol``, ``--o2``, ``--coils``)
  mirror CAFlash prompts so selections are logged alongside each flash event.

The implementation keeps protocol logic explicit so the script can serve as a
starting point for vehicle testing. Attachments should be limited to USB CAN
interfaces such as K+DCAN (Lawicel/slcan), PCAN, or the Bavarian Technic
diagnostic cable (via its J2534 driver) running at 500 kbit/s.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import platform
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Protocol

try:
    import can  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency for python-can back ends
    can = None  # type: ignore

###############################################################################
# Logging
###############################################################################
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
LOG = logging.getLogger("n54flash")

###############################################################################
# Constants – CAN IDs & service IDs
###############################################################################
CAN_ID_REQ = 0x6F1  # Tester ➜ ECU
CAN_ID_RESP = 0x6F9  # ECU ➜ Tester

POS_RESP = 0x40

SID_START_SESSION = 0x10
SID_ECU_RESET = 0x11
SID_SECURITY_ACCESS = 0x27
SID_TESTER_PRESENT = 0x3E
SID_READ_ECU_ID = 0x1A
SID_READ_MEMORY_BY_ADDR = 0x23
SID_REQUEST_DOWNLOAD = 0x34
SID_TRANSFER_DATA = 0x36
SID_REQUEST_TRANSFER_EXIT = 0x37
SID_ROUTINE_CONTROL = 0x31  # erase routines

ROUTINE_ERASE_ALL = 0xFF00

###############################################################################
# Flash layout & parameters
###############################################################################
SECTOR_MAP = [
    {"name": "BOOT", "addr": 0x000000, "size": 0x010000, "protected": True},
    {"name": "CAL", "addr": 0x010000, "size": 0x040000, "protected": False},
    {"name": "CODE", "addr": 0x050000, "size": 0x0B0000, "protected": True},
]
FLASH_SIZE = 0x100000  # 1 MiB total
TRANSFER_SIZE_DEFAULT = 0x0800  # 2 KiB default block
TESTER_PRESENT_INTERVAL = 2.0

CAL_START = SECTOR_MAP[1]["addr"]
CAL_SIZE = SECTOR_MAP[1]["size"]
CAL_END = CAL_START + CAL_SIZE


###############################################################################
# Frame helpers
###############################################################################


@dataclass
class Frame:
    arbitration_id: int
    data: bytes


class FrameBus(Protocol):
    def send(self, frame: Frame) -> None:
        ...

    def recv(self, timeout: float) -> Optional[Frame]:
        ...

    def shutdown(self) -> None:  # pragma: no cover - optional cleanup hook
        ...


class PythonCanBusAdapter:
    """Adapter that wraps a python-can Bus and exposes the FrameBus protocol."""

    def __init__(self, bus: can.BusABC):
        self._bus = bus

    def send(self, frame: Frame) -> None:
        message = can.Message(
            arbitration_id=frame.arbitration_id,
            data=frame.data,
            is_extended_id=False,
        )
        self._bus.send(message)

    def recv(self, timeout: float) -> Optional[Frame]:
        message = self._bus.recv(timeout)
        if not message:
            return None
        return Frame(message.arbitration_id, bytes(message.data))

    def shutdown(self) -> None:
        try:
            self._bus.shutdown()
        except AttributeError:  # pragma: no cover - older python-can versions
            pass


class J2534Error(RuntimeError):
    """Raised when a J2534 API call fails."""


class BavarianTechnicBus:
    """J2534-based FrameBus implementation for the Bavarian Technic USB cable."""

    PROTOCOL_CAN = 0x00000002
    PASS_FILTER = 0x00000001
    SET_CONFIG = 0x00000001
    ERR_TIMEOUT = 0x0000000A
    ERR_BUFFER_EMPTY = 0x00000007
    DATA_BUFFER_SIZE = 4128

    class PASSTHRU_MSG(ctypes.Structure):
        _fields_ = [
            ("ProtocolID", ctypes.c_ulong),
            ("RxStatus", ctypes.c_ulong),
            ("TxFlags", ctypes.c_ulong),
            ("Timestamp", ctypes.c_ulong),
            ("DataSize", ctypes.c_ulong),
            ("ExtraDataIndex", ctypes.c_ulong),
            ("Data", ctypes.c_ubyte * DATA_BUFFER_SIZE),
        ]

    class SCONFIG(ctypes.Structure):
        _fields_ = [("Parameter", ctypes.c_ulong), ("Value", ctypes.c_ulong)]

    class SCONFIG_LIST(ctypes.Structure):
        _fields_ = [("NumOfParams", ctypes.c_ulong), ("ConfigPtr", ctypes.POINTER(SCONFIG))]

    def __init__(self, dll_path: Path | str, channel: int = 0, bitrate: int = 500000):
        if platform.system() != "Windows":
            raise RuntimeError("The Bavarian Technic driver is only available on Windows")

        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"J2534 DLL not found: {dll_path}")

        self._dll = ctypes.WinDLL(str(dll_path))
        self._configure_prototypes()
        self._device_id = ctypes.c_ulong()
        self._channel_id = ctypes.c_ulong()
        self._filter_id = ctypes.c_ulong()
        self._bitrate = bitrate
        self._tx_timeout = 1000  # milliseconds
        self._lock = threading.Lock()

        self._open_device()
        self._connect(channel)
        self._apply_bitrate()
        self._install_pass_filter()

    # ------------------------------------------------------------------
    # Public FrameBus API
    def send(self, frame: Frame) -> None:
        msg = self.PASSTHRU_MSG()
        msg.ProtocolID = self.PROTOCOL_CAN
        msg.DataSize = len(frame.data) + 4
        msg.ExtraDataIndex = 4
        arb = frame.arbitration_id & 0x1FFFFFFF
        msg.Data[0] = arb & 0xFF
        msg.Data[1] = (arb >> 8) & 0xFF
        msg.Data[2] = (arb >> 16) & 0xFF
        msg.Data[3] = (arb >> 24) & 0xFF
        for idx, byte in enumerate(frame.data):
            msg.Data[4 + idx] = byte

        count = ctypes.c_ulong(1)
        with self._lock:
            status = self._dll.PassThruWriteMsgs(
                self._channel_id, ctypes.byref(msg), ctypes.byref(count), self._tx_timeout
            )
        self._check(status, "PassThruWriteMsgs")

    def recv(self, timeout: float) -> Optional[Frame]:
        msg = self.PASSTHRU_MSG()
        count = ctypes.c_ulong(1)
        timeout_ms = int(max(timeout, 0) * 1000)
        with self._lock:
            status = self._dll.PassThruReadMsgs(
                self._channel_id, ctypes.byref(msg), ctypes.byref(count), timeout_ms
            )

        if status in (self.ERR_TIMEOUT, self.ERR_BUFFER_EMPTY):
            return None
        self._check(status, "PassThruReadMsgs")
        if count.value == 0:
            return None

        arb = msg.Data[0] | (msg.Data[1] << 8) | (msg.Data[2] << 16) | (msg.Data[3] << 24)
        payload_length = int(msg.DataSize) - 4
        payload_length = max(0, min(payload_length, len(msg.Data) - 4))
        data = bytes(msg.Data[4 : 4 + payload_length])
        return Frame(arb, data)

    def shutdown(self) -> None:
        with self._lock:
            if self._filter_id.value:
                self._dll.PassThruStopMsgFilter(self._channel_id, self._filter_id)
                self._filter_id.value = 0
            if self._channel_id.value:
                self._dll.PassThruDisconnect(self._channel_id)
                self._channel_id.value = 0
            if self._device_id.value:
                self._dll.PassThruClose(self._device_id)
                self._device_id.value = 0

    # ------------------------------------------------------------------
    # Internal helpers
    def _check(self, status: int, api: str) -> None:
        if status != 0:
            raise J2534Error(f"{api} failed with status 0x{status:08X}")

    def _configure_prototypes(self) -> None:
        self._dll.PassThruOpen.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self._dll.PassThruOpen.restype = ctypes.c_ulong
        self._dll.PassThruClose.argtypes = [ctypes.c_ulong]
        self._dll.PassThruClose.restype = ctypes.c_ulong
        self._dll.PassThruConnect.argtypes = [
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self._dll.PassThruConnect.restype = ctypes.c_ulong
        self._dll.PassThruDisconnect.argtypes = [ctypes.c_ulong]
        self._dll.PassThruDisconnect.restype = ctypes.c_ulong
        self._dll.PassThruReadMsgs.argtypes = [
            ctypes.c_ulong,
            ctypes.POINTER(self.PASSTHRU_MSG),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_ulong,
        ]
        self._dll.PassThruReadMsgs.restype = ctypes.c_ulong
        self._dll.PassThruWriteMsgs.argtypes = [
            ctypes.c_ulong,
            ctypes.POINTER(self.PASSTHRU_MSG),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_ulong,
        ]
        self._dll.PassThruWriteMsgs.restype = ctypes.c_ulong
        self._dll.PassThruStartMsgFilter.argtypes = [
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(self.PASSTHRU_MSG),
            ctypes.POINTER(self.PASSTHRU_MSG),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self._dll.PassThruStartMsgFilter.restype = ctypes.c_ulong
        self._dll.PassThruStopMsgFilter.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self._dll.PassThruStopMsgFilter.restype = ctypes.c_ulong
        self._dll.PassThruIoctl.argtypes = [
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._dll.PassThruIoctl.restype = ctypes.c_ulong

    def _open_device(self) -> None:
        status = self._dll.PassThruOpen(None, ctypes.byref(self._device_id))
        self._check(status, "PassThruOpen")

    def _connect(self, channel: int) -> None:
        _ = channel  # channel selection is handled within the vendor driver
        channel_id = ctypes.c_ulong()
        status = self._dll.PassThruConnect(
            self._device_id, self.PROTOCOL_CAN, 0, self._bitrate, ctypes.byref(channel_id)
        )
        self._check(status, "PassThruConnect")
        self._channel_id = channel_id

    def _apply_bitrate(self) -> None:
        sconfig = self.SCONFIG(1, self._bitrate)
        sconfig_list = self.SCONFIG_LIST(1, ctypes.pointer(sconfig))
        status = self._dll.PassThruIoctl(
            self._channel_id, self.SET_CONFIG, ctypes.byref(sconfig_list), None
        )
        self._check(status, "PassThruIoctl(SET_CONFIG)")

    def _install_pass_filter(self) -> None:
        mask = self.PASSTHRU_MSG()
        pattern = self.PASSTHRU_MSG()
        mask.ProtocolID = self.PROTOCOL_CAN
        pattern.ProtocolID = self.PROTOCOL_CAN
        mask.DataSize = pattern.DataSize = 4
        mask.ExtraDataIndex = pattern.ExtraDataIndex = 4
        filter_id = ctypes.c_ulong()
        status = self._dll.PassThruStartMsgFilter(
            self._channel_id,
            self.PASS_FILTER,
            ctypes.byref(mask),
            ctypes.byref(pattern),
            None,
            ctypes.byref(filter_id),
        )
        self._check(status, "PassThruStartMsgFilter")
        self._filter_id = filter_id

    def __del__(self):  # pragma: no cover - cleanup best-effort only
        try:
            self.shutdown()
        except Exception:
            pass


###############################################################################
# Seed→key algorithm for MSD80/81
###############################################################################

def calc_key_msd80(seed: int) -> int:
    """16-bit XOR algorithm used by MSD80/81."""

    return ((seed ^ 0x5A3C) + 0x7F1B) & 0xFFFF


###############################################################################
# Minimal ISO-TP implementation
###############################################################################


class IsoTp:
    """Tiny ISO-TP helper that operates on top of an abstract CAN frame bus."""

    def __init__(self, bus: FrameBus, tx_id: int, rx_id: int, timeout: float = 1.0):
        self.bus, self.tx_id, self.rx_id, self.timeout = bus, tx_id, rx_id, timeout

    def request(self, payload: bytes, expect_resp: bool = True) -> Optional[bytes]:
        self._send(payload)
        return self._recv() if expect_resp else None

    # --- internal helpers --------------------------------------------------
    def _send(self, payload: bytes) -> None:
        if len(payload) <= 7:
            frame = bytes([len(payload)]) + payload + b"\x00" * (7 - len(payload))
            self.bus.send(Frame(self.tx_id, frame))
            return

        total = len(payload)
        ff = bytes([0x10 | ((total >> 8) & 0x0F), total & 0xFF]) + payload[:6]
        self.bus.send(Frame(self.tx_id, ff))
        fc = self._recv(raw=True)
        if not fc or fc[0] >> 4 != 0x3:
            raise RuntimeError("No FlowControl")
        st_min, bs = fc[2], fc[1]
        ptr, sn, bs_cnt = 6, 1, 0
        while ptr < total:
            chunk = payload[ptr : ptr + 7]
            cf = bytes([0x20 | (sn & 0x0F)]) + chunk + b"\x00" * (7 - len(chunk))
            self.bus.send(Frame(self.tx_id, cf))
            ptr += len(chunk)
            sn = (sn + 1) & 0x0F
            bs_cnt += 1
            if bs and bs_cnt >= bs:
                bs_cnt = 0
                fc = self._recv(raw=True)
                if not fc or fc[0] >> 4 != 0x3:
                    raise RuntimeError("Missing FC mid-transfer")
                st_min, bs = fc[2], fc[1]
            if st_min <= 0x7F:
                time.sleep(st_min / 1000.0)

    def _recv(self, raw: bool = False) -> Optional[bytes]:
        msg = self.bus.recv(self.timeout)
        if not msg or msg.arbitration_id != self.rx_id:
            return None
        data = bytes(msg.data)
        if raw:
            return data
        ptype = data[0] & 0xF0
        if ptype == 0x00:
            return data[1 : 1 + (data[0] & 0x0F)]
        if ptype == 0x10:
            total = ((data[0] & 0x0F) << 8) | data[1]
            buf = bytearray(data[2:8])
            self.bus.send(Frame(self.tx_id, b"\x30\x00\x00" + b"\x00" * 5))
            while len(buf) < total:
                cf = self.bus.recv(self.timeout)
                if not cf or cf.arbitration_id != self.rx_id:
                    raise RuntimeError("Consecutive frame timeout")
                buf.extend(cf.data[1:])
            return bytes(buf[:total])
        return None


###############################################################################
# KWP helper
###############################################################################


def pos(sid: int) -> int:
    return sid + POS_RESP


###############################################################################
# Tester-present helper
###############################################################################


class TesterPresentThread(threading.Thread):
    def __init__(self, flasher: "Flasher", interval: float = TESTER_PRESENT_INTERVAL):
        super().__init__(daemon=True)
        self._flasher = flasher
        self._interval = interval
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._flasher._kwp(SID_TESTER_PRESENT, b"\x00")  # noqa: SLF001
            except Exception as exc:  # pragma: no cover - best-effort logging only
                LOG.warning("TesterPresent failed: %s", exc)
            finally:
                self._stop.wait(self._interval)


###############################################################################
# Flasher
###############################################################################


class Flasher:
    def __init__(self, bus: FrameBus, timeout: float = 1.0):
        self.bus = bus
        self.tp = IsoTp(bus, CAN_ID_REQ, CAN_ID_RESP, timeout=timeout)

    # ----- Low-level -------------------------------------------------------
    def _kwp(self, sid: int, payload: bytes | List[int], *, expect_resp: bool = True) -> bytes:
        if isinstance(payload, list):
            payload = bytes(payload)
        resp = self.tp.request(bytes([sid]) + payload, expect_resp=expect_resp)
        return resp or b""

    # ----- Session & security ---------------------------------------------
    def enter_session(self) -> None:
        resp = self._kwp(SID_START_SESSION, b"\x85")
        if not resp or resp[0] != pos(SID_START_SESSION):
            raise RuntimeError("Cannot enter programming session")
        LOG.info("Programming session active")

    def security_unlock(self) -> None:
        seed_r = self._kwp(SID_SECURITY_ACCESS, b"\x01")
        if not seed_r or seed_r[0] != pos(SID_SECURITY_ACCESS):
            raise RuntimeError("Seed request failed")
        seed = int.from_bytes(seed_r[2:4], "big")
        key = calc_key_msd80(seed)
        key_r = self._kwp(SID_SECURITY_ACCESS, bytes([0x02, key >> 8, key & 0xFF]))
        if not key_r or key_r[0] != pos(SID_SECURITY_ACCESS):
            raise RuntimeError("Security key rejected")
        LOG.info("Security access granted")

    # ----- Information -----------------------------------------------------
    def read_ecu_id(self) -> dict[str, bytes]:
        identifiers: Iterable[bytes] = [b"\x90", b"\x92", b"\x94", b"\x97"]
        result: dict[str, bytes] = {}
        for ident in identifiers:
            resp = self._kwp(SID_READ_ECU_ID, ident)
            if resp and resp[0] == pos(SID_READ_ECU_ID):
                label = f"0x{ident.hex()}"
                result[label] = resp[2:]
        return result

    # ----- Memory helpers --------------------------------------------------
    def read_block(self, addr: int, length: int) -> bytes:
        if length <= 0 or length > 0xFFFF:
            raise ValueError("Length must be 1..65535 bytes")
        payload = bytes([0x24]) + addr.to_bytes(4, "big") + bytes([0x24]) + length.to_bytes(4, "big")
        resp = self._kwp(SID_READ_MEMORY_BY_ADDR, payload)
        if not resp or resp[0] != pos(SID_READ_MEMORY_BY_ADDR):
            raise RuntimeError("ReadMemoryByAddress failed")
        return resp[1:]

    def erase_all(self) -> None:
        LOG.info("Starting erase routine")
        payload = bytes([0x01, ROUTINE_ERASE_ALL >> 8, ROUTINE_ERASE_ALL & 0xFF])
        resp = self._kwp(SID_ROUTINE_CONTROL, payload)
        if not resp or resp[0] != pos(SID_ROUTINE_CONTROL):
            raise RuntimeError("Erase routine rejected")
        LOG.info("Erase routine acknowledged")

    def request_download(self, addr: int, length: int) -> int:
        payload = bytes([0x00, 0x44]) + addr.to_bytes(4, "big") + length.to_bytes(4, "big")
        resp = self._kwp(SID_REQUEST_DOWNLOAD, payload)
        if not resp or resp[0] != pos(SID_REQUEST_DOWNLOAD):
            raise RuntimeError("RequestDownload rejected")
        max_len_len = resp[1]
        max_len = int.from_bytes(resp[2 : 2 + max_len_len], "big") if max_len_len else TRANSFER_SIZE_DEFAULT
        LOG.info("ECU reports %d byte max transfer block", max_len)
        return max_len

    def transfer_data(self, data: bytes, chunk_size: int) -> None:
        counter = 1
        offset = 0
        total = len(data)
        while offset < total:
            chunk = data[offset : offset + chunk_size]
            payload = bytes([counter & 0xFF]) + chunk
            resp = self._kwp(SID_TRANSFER_DATA, payload)
            if not resp or resp[0] != pos(SID_TRANSFER_DATA):
                raise RuntimeError(f"TransferData failed at block {counter}")
            offset += len(chunk)
            counter = (counter + 1) & 0xFF
            LOG.debug("Transferred %d/%d bytes", offset, total)

    def transfer_exit(self) -> None:
        resp = self._kwp(SID_REQUEST_TRANSFER_EXIT, b"")
        if not resp or resp[0] != pos(SID_REQUEST_TRANSFER_EXIT):
            raise RuntimeError("TransferExit failed")

    # ----- High level operations ------------------------------------------
    def backup(self, output: Path, *, chunk: int = 0x0400) -> None:
        LOG.info("Backing up flash to %s", output)
        buf = bytearray()
        with open(output, "wb") as handle:
            for addr in range(0, FLASH_SIZE, chunk):
                data = self.read_block(addr, min(chunk, FLASH_SIZE - addr))
                handle.write(data)
                buf.extend(data)
                LOG.info("Read 0x%06X-0x%06X", addr, addr + len(data))
        LOG.info("Backup complete (%d bytes)", len(buf))

    def flash(self, image: bytes, *, chunk_size: int = TRANSFER_SIZE_DEFAULT) -> None:
        if len(image) != FLASH_SIZE:
            raise ValueError("Image must be exactly 1 MiB")
        self.erase_all()
        max_chunk = self.request_download(0, len(image))
        block = min(chunk_size, max_chunk)
        LOG.info("Programming with %d-byte blocks", block)
        tester = TesterPresentThread(self)
        tester.start()
        try:
            self.transfer_data(image, block)
            self.transfer_exit()
        finally:
            tester.stop()
            tester.join(timeout=2)
        LOG.info("Flash programming complete")

    def verify(self, image: bytes, *, chunk: int = 0x0400) -> None:
        LOG.info("Verifying flash contents")
        for addr in range(0, len(image), chunk):
            data = self.read_block(addr, min(chunk, len(image) - addr))
            if data != image[addr : addr + len(data)]:
                raise RuntimeError(f"Verification mismatch at 0x{addr:06X}")
        LOG.info("Verification successful")


###############################################################################
# VIN patch helpers
###############################################################################


def patch_vin(image: bytes, new_vin: str) -> bytes:
    if len(new_vin) != 17:
        raise ValueError("VIN must be exactly 17 characters")
    buf = bytearray(image)
    vin_bytes = new_vin.encode("ascii")
    cal_region = buf[CAL_START:CAL_END]
    idx = cal_region.find(vin_bytes)
    if idx == -1:
        raise RuntimeError("Existing VIN not found in calibration area")
    abs_idx = CAL_START + idx
    buf[abs_idx : abs_idx + 17] = vin_bytes
    LOG.info("Patched VIN at 0x%06X", abs_idx)
    _fix_cal_checksum(buf)
    return bytes(buf)


def _fix_cal_checksum(buf: bytearray) -> None:
    """Adjust the final 16-bit checksum word so the additive sum is zero."""

    cal = buf[CAL_START:CAL_END]
    words = struct.iter_unpack(">H", cal[:-2])
    checksum = sum(word for (word,) in words) & 0xFFFF
    corrected = (-checksum) & 0xFFFF
    buf[CAL_END - 2 : CAL_END] = corrected.to_bytes(2, "big")
    LOG.info("Updated CAL checksum to 0x%04X", corrected)


###############################################################################
# CLI
###############################################################################


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BMW N54 MSD80 flasher")
    parser.add_argument(
        "--iface",
        choices=["slcan", "pcan", "bavtech"],
        default="slcan",
        help="Interface backend: python-can (slcan/pcan) or Bavarian Technic J2534",
    )
    parser.add_argument(
        "--channel",
        default="/dev/ttyUSB0",
        help="python-can channel (default: /dev/ttyUSB0 for slcan or PCAN_USBBUS1)",
    )
    parser.add_argument("--bitrate", type=int, default=500000, help="CAN bitrate (default: 500000)")
    parser.add_argument("--timeout", type=float, default=1.0, help="CAN receive timeout")
    parser.add_argument("--info", action="store_true", help="Print ECU identity")
    parser.add_argument("--backup", type=Path, help="Dump full flash to the given file")
    parser.add_argument("--flash", dest="flash_path", type=Path, help="Program the supplied image")
    parser.add_argument("--vin", dest="vin", help="Patch VIN before flashing")
    parser.add_argument("--chunk", type=int, default=TRANSFER_SIZE_DEFAULT, help="Transfer chunk size override")
    parser.add_argument("--tmap", choices=["stock", "3.5bar"], help="TMAP configuration for logging")
    parser.add_argument(
        "--ethanol",
        choices=["0-20%", "20-40%", "40-60%", "60%+"],
        help="Ethanol content range for logging",
    )
    parser.add_argument("--o2", choices=["stock", "single"], help="O2 sensor configuration for logging")
    parser.add_argument(
        "--coils",
        choices=["stock", "b58", "precision", "bimmerlife"],
        help="Ignition coil setup for logging",
    )
    parser.add_argument("--notes", help="Free-form notes recorded with flash metadata")
    parser.add_argument(
        "--bt-dll",
        type=Path,
        help="Path to the Bavarian Technic J2534 DLL (or set BAVTECH_DLL)",
    )
    parser.add_argument(
        "--bt-channel",
        type=int,
        default=0,
        help="Bavarian Technic channel index (default: 0)",
    )
    return parser.parse_args()


def open_bus(args: argparse.Namespace) -> FrameBus:
    if args.iface == "bavtech":
        dll_path: Optional[Path]
        if args.bt_dll:
            dll_path = args.bt_dll
        else:
            env = os.environ.get("BAVTECH_DLL")
            dll_path = Path(env) if env else None
        if not dll_path:
            raise SystemExit("Provide --bt-dll or set the BAVTECH_DLL environment variable")
        LOG.info(
            "Opening Bavarian Technic J2534 driver %s (channel %d) @ %d",
            dll_path,
            args.bt_channel,
            args.bitrate,
        )
        return BavarianTechnicBus(dll_path, channel=args.bt_channel, bitrate=args.bitrate)

    if can is None:  # pragma: no cover - optional dependency guard
        raise SystemExit("python-can is not installed; unable to use %s" % args.iface)

    LOG.info("Opening %s on %s @ %d", args.iface, args.channel, args.bitrate)
    bus = can.Bus(interface=args.iface, channel=args.channel, bitrate=args.bitrate)
    return PythonCanBusAdapter(bus)


def describe_flash_profile(args: argparse.Namespace) -> None:
    selections: list[str] = []
    if args.tmap:
        selections.append(f"TMAP={args.tmap}")
    if args.ethanol:
        selections.append(f"Ethanol={args.ethanol}")
    if args.o2:
        selections.append(f"O2={args.o2}")
    if args.coils:
        selections.append(f"Coils={args.coils}")
    if args.notes:
        selections.append(f"Notes={args.notes}")
    if selections:
        LOG.info("Flash profile: %s", ", ".join(selections))


def main() -> None:
    args = parse_args()
    if not any([args.info, args.backup, args.flash_path]):
        raise SystemExit("No action requested -- use --info, --backup, or --flash")

    bus = open_bus(args)
    flasher = Flasher(bus, timeout=args.timeout)

    try:
        flasher.enter_session()
        flasher.security_unlock()

        if args.info:
            ecu_ids = flasher.read_ecu_id()
            if ecu_ids:
                for key, value in ecu_ids.items():
                    LOG.info("ECU ID %s: %s", key, value.hex())
            else:
                LOG.warning("ECU did not return any identifiers")

        if args.backup:
            flasher.backup(args.backup)

        if args.flash_path:
            image = args.flash_path.read_bytes()
            if args.vin:
                image = patch_vin(image, args.vin)
            describe_flash_profile(args)
            flasher.flash(image, chunk_size=args.chunk)
            flasher.verify(image)

        LOG.info("All requested operations completed")
    finally:
        try:
            bus.shutdown()
        except Exception as exc:  # pragma: no cover - best effort shutdown
            LOG.debug("Bus shutdown raised %s", exc)


if __name__ == "__main__":
    main()
