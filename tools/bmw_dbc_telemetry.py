"""In memory telemetry helpers used by the demonstration Flask server."""

from __future__ import annotations

from dataclasses import dataclass
import random
import threading
import time
from typing import Callable, Dict, List, Optional


@dataclass
class TelemetryPoint:
    """Container describing a single telemetry snapshot."""

    timestamp: float
    signals: Dict[str, float]
    calculated: Dict[str, float]


@dataclass
class SignalDefinition:
    """Light weight structure that mirrors a DBC signal."""

    name: str
    unit: str


class BMWSignals:
    """Factory for a couple of built-in telemetry definitions."""

    DEFAULT_SIGNALS = {
        "ENGINE_RPM": SignalDefinition("ENGINE_RPM", "rpm"),
        "BOOST_PRESSURE": SignalDefinition("BOOST_PRESSURE", "bar"),
        "COOLANT_TEMP": SignalDefinition("COOLANT_TEMP", "°C"),
    }

    @classmethod
    def create_database(cls, series: str) -> Dict[str, SignalDefinition]:
        # The simulated project keeps things simple and always returns the same
        # base signal set regardless of the requested series.  The hook is still
        # useful for future expansion and keeps the public API matching the real
        # tooling.
        return dict(cls.DEFAULT_SIGNALS)


class LiveTelemetrySession:
    """Generate pseudo random telemetry points for the web interface."""

    def __init__(self, signals: Dict[str, SignalDefinition]) -> None:
        self._signals = signals
        self._callbacks: List[Callable[[TelemetryPoint], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def add_callback(self, callback: Callable[[TelemetryPoint], None]) -> None:
        self._callbacks.append(callback)
        if not self._thread or not self._thread.is_alive():
            self._start()

    def _start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop.is_set():
            timestamp = time.time()
            signals: Dict[str, float] = {}
            for name, definition in self._signals.items():
                if definition.unit == "rpm":
                    signals[name] = random.uniform(700.0, 7000.0)
                elif definition.unit == "bar":
                    signals[name] = random.uniform(0.8, 1.6)
                elif definition.unit == "°C":
                    signals[name] = random.uniform(70.0, 110.0)
                else:
                    signals[name] = random.random()

            calculated = {
                "power_kw": signals.get("ENGINE_RPM", 0.0) * 0.001,
                "boost_psi": signals.get("BOOST_PRESSURE", 0.0) * 14.5038,
            }

            point = TelemetryPoint(timestamp=timestamp, signals=signals, calculated=calculated)
            for callback in list(self._callbacks):
                callback(point)
            time.sleep(1.0)


__all__ = [
    "BMWSignals",
    "LiveTelemetrySession",
    "TelemetryPoint",
]

