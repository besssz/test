"""Minimal XDF helpers for the simulated flashing web UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class AxisDefinition:
    address: int
    count: int
    scale: float
    offset: float

    def read_values(self, data: bytes, endian: str = "big") -> List[float]:
        values: List[float] = []
        for idx in range(self.count):
            start = self.address + (idx * 2)
            raw = int.from_bytes(data[start : start + 2], endian)
            values.append(raw * self.scale + self.offset)
        return values


@dataclass
class MapTable:
    name: str
    category: str
    address: int
    rows: int
    cols: int
    unit: str
    description: str
    x_axis: Optional[AxisDefinition] = None
    y_axis: Optional[AxisDefinition] = None


class XDFParser:
    def __init__(self, tables: Dict[str, MapTable], endian: str = "big") -> None:
        self.tables = tables
        self.endian = endian

    def get_table(self, name: str) -> MapTable:
        return self.tables[name]


class CommonMaps:
    """Factory that builds a small selection of fake maps."""

    @staticmethod
    def create_definition(ecu_type: str) -> XDFParser:
        base = 0x10000 if ecu_type.startswith("MSD8") else 0x20000
        maps = {
            "Boost Target": MapTable(
                name="Boost Target",
                category="Engine",
                address=base,
                rows=8,
                cols=8,
                unit="bar",
                description="Requested boost pressure",
                x_axis=AxisDefinition(base + 0x100, 8, 0.01, 0.0),
                y_axis=AxisDefinition(base + 0x200, 8, 10.0, 0.0),
            ),
            "Fuel Scalar": MapTable(
                name="Fuel Scalar",
                category="Fuel",
                address=base + 0x400,
                rows=4,
                cols=4,
                unit="λ",
                description="Fuel mixture target",
            ),
        }
        return XDFParser(maps, endian="big")


class MapEditor:
    def __init__(self, xdf: XDFParser, flash_data: bytes) -> None:
        self._xdf = xdf
        self._data = flash_data

    def read_table(self, name: str) -> Optional[List[List[float]]]:
        if name not in self._xdf.tables:
            return None
        table = self._xdf.tables[name]
        result: List[List[float]] = []
        for row in range(table.rows):
            row_values: List[float] = []
            for col in range(table.cols):
                offset = table.address + (row * table.cols + col) * 2
                raw = int.from_bytes(self._data[offset : offset + 2], self._xdf.endian)
                row_values.append(raw / 100.0)
            result.append(row_values)
        return result


__all__ = [
    "AxisDefinition",
    "CommonMaps",
    "MapEditor",
    "MapTable",
    "XDFParser",
]

