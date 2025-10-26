"""Tests for MSD80 ECU identity decoding."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.n54flash import (  # type: ignore[import-not-found]
    ECU_ID_LABELS,
    SID_READ_ECU_ID,
    EcuIdentity,
    Flasher,
    _decode_ascii_field,
    pos,
)


class DummyFlasher(Flasher):
    def __init__(self, responses: dict[int, bytes]):
        # Skip parent initialisation – tests only need the KWP helper.
        self._responses = responses

    def _kwp(self, sid: int, payload, *, expect_resp: bool = True):  # type: ignore[override]
        identifier = payload[0] if isinstance(payload, (bytes, bytearray)) else payload
        return self._responses.get(identifier)


KNOWN_ID_RESPONSES = {
    0x90: bytes([pos(SID_READ_ECU_ID), 0x90]) + b"WBAVB73587PA12345",
    0x92: bytes([pos(SID_READ_ECU_ID), 0x92]) + b"7562150",
    0x94: bytes([pos(SID_READ_ECU_ID), 0x94]) + b"1037393801",
    0x97: bytes([pos(SID_READ_ECU_ID), 0x97]) + b"080123456789",
}


def test_ascii_decoder_strips_padding():
    assert _decode_ascii_field(b"12345\x00\x00") == "12345"
    assert _decode_ascii_field(b"  VIN123  ") == "VIN123"


def test_read_ecu_id_decodes_known_msd80_identity():
    flasher = DummyFlasher(KNOWN_ID_RESPONSES)
    identity = flasher.read_ecu_id()

    assert isinstance(identity, EcuIdentity)
    for ident, label in ECU_ID_LABELS.items():
        assert identity.decoded[label]
        assert identity.raw[ident] == KNOWN_ID_RESPONSES[ident][2:]

    assert identity.decoded["VIN"] == "WBAVB73587PA12345"
    assert identity.decoded["ECU HW"] == "7562150"
    assert identity.decoded["ECU SW"] == "1037393801"
    assert identity.decoded["ECU CAL"] == "080123456789"
