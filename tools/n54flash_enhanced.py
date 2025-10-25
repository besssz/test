"""High level wrappers around :mod:`tools.n54flash` for the web API.

The original ``n54flash`` module contains the production-ready logic for
communicating with Siemens MSD80/81 control units.  The Flask server consumed by
our frontend only needs a subset of the CLI behaviour, so this module provides a
thin layer that exposes the same objects the HTTP handlers expect while routing
all work through the real flasher implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from . import n54flash

LOG = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int], None]]


class EdiabasLibBackend:
    """Wrapper that opens the requested interface using :func:`n54flash.open_bus`.

    The name matches the previous simulated implementation so the web server can
    keep its import path unchanged.  All operations are carried out by the real
    ``Flasher`` class from :mod:`tools.n54flash`.
    """

    def __init__(self, args):
        self.args = args
        self.bus = n54flash.open_bus(args)
        timeout = getattr(args, "timeout", 1.0)
        self.flasher = n54flash.Flasher(self.bus, timeout=timeout)

    def read_vbat(self) -> Optional[float]:
        """Return ``None`` – MSD80 does not expose battery voltage via KWP."""

        return None

    def close(self) -> None:
        """Close the underlying bus if it exposes a ``shutdown`` hook."""

        try:
            self.bus.shutdown()
        except AttributeError:
            pass


@dataclass
class FlashImage:
    """Container for flash image bytes with helper utilities."""

    data: bytes
    ecu_type: str

    def validate(self) -> tuple[bool, str]:
        """Perform basic validation on the supplied image."""

        if len(self.data) != n54flash.FLASH_SIZE:
            return False, "Image must be exactly 1 MiB for MSD80/81"

        if all(b == 0xFF for b in self.data[:32]):
            return False, "Image appears to be blank"

        return True, "Image validated successfully"

    def patch_vin(self, vin: str) -> bytes:
        """Patch the VIN using the helper from :mod:`n54flash`."""

        return n54flash.patch_vin(self.data, vin)


class FlashController:
    """Expose high level operations used by the web server."""

    def __init__(self, backend: EdiabasLibBackend, ecu_type: str):
        self.backend = backend
        self.ecu_type = ecu_type

    # ------------------------------------------------------------------
    # Information
    def read_ecu_info(self) -> Dict[str, str]:
        flasher = self.backend.flasher
        flasher.enter_session()
        info_raw = flasher.read_ecu_id()

        info: Dict[str, str] = {}
        for key, payload in info_raw.items():
            text = payload.rstrip(b"\x00")
            if text:
                try:
                    decoded = text.decode("ascii")
                except UnicodeDecodeError:
                    decoded = text.hex()
            else:
                decoded = ""
            info[key] = decoded
        return info

    # ------------------------------------------------------------------
    # Backup & flash
    def backup_flash(self, output_path: Path, progress_callback: ProgressCallback = None) -> bool:
        flasher = self.backend.flasher
        try:
            flasher.enter_session()
            flasher.security_unlock()
            total = n54flash.FLASH_SIZE
            chunk = 0x0400
            read = 0
            with output_path.open("wb") as handle:
                for addr in range(0, total, chunk):
                    block = flasher.read_block(addr, min(chunk, total - addr))
                    handle.write(block)
                    read += len(block)
                    if progress_callback:
                        progress_callback(read, total)
            return True
        except Exception:
            LOG.exception("Flash backup failed")
            return False

    def flash_image(self, image: FlashImage, progress_callback: ProgressCallback = None) -> bool:
        valid, message = image.validate()
        if not valid:
            LOG.error("Image validation failed: %s", message)
            return False

        flasher = self.backend.flasher
        data = image.data

        try:
            flasher.enter_session()
            flasher.security_unlock()
            flasher.erase_all()
            max_chunk = flasher.request_download(0, len(data))
            chunk = min(n54flash.TRANSFER_SIZE_DEFAULT, max_chunk)
            tester = n54flash.TesterPresentThread(flasher)
            tester.start()
            try:
                self._transfer_with_progress(flasher, data, chunk, progress_callback)
                flasher.transfer_exit()
            finally:
                tester.stop()
                tester.join(timeout=2)

            flasher.verify(data)
            if progress_callback:
                progress_callback(len(data), len(data))
            return True
        except Exception:
            LOG.exception("Flash operation failed")
            return False

    # ------------------------------------------------------------------
    # Helpers
    @staticmethod
    def _transfer_with_progress(
        flasher: n54flash.Flasher,
        data: bytes,
        chunk_size: int,
        progress_callback: ProgressCallback,
    ) -> None:
        total = len(data)
        counter = 1
        offset = 0
        while offset < total:
            chunk = data[offset : offset + chunk_size]
            payload = bytes([counter & 0xFF]) + chunk
            resp = flasher._kwp(n54flash.SID_TRANSFER_DATA, payload)  # noqa: SLF001
            if not resp or resp[0] != n54flash.pos(n54flash.SID_TRANSFER_DATA):
                raise RuntimeError(f"TransferData failed at block {counter}")
            offset += len(chunk)
            counter = (counter + 1) & 0xFF
            if progress_callback:
                progress_callback(offset, total)
