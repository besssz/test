"""Flask based façade that exposes the production flashing backend."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    from flask_socketio import SocketIO
except ModuleNotFoundError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit(
        "Flask and Flask-SocketIO are required to run the demo server"
    ) from exc

from .bmw_dbc_telemetry import BMWSignals, LiveTelemetrySession
from .bmw_xdf_tuning import CommonMaps, MapEditor
from .n54flash_enhanced import EdiabasLibBackend, FlashController, FlashImage


LOG = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "bmw-flash-tool-secret"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")


@dataclass
class ServerState:
    backend: Optional[EdiabasLibBackend] = None
    controller: Optional[FlashController] = None
    telemetry_session: Optional[LiveTelemetrySession] = None
    current_operation: Optional[str] = None
    progress: int = 0
    logs: list[Dict[str, Any]] = field(default_factory=list)


state = ServerState()


def emit_log(message: str, level: str = "info") -> None:
    entry = {"timestamp": time.time(), "message": message, "level": level}
    state.logs.append(entry)
    socketio.emit("log", entry)


def emit_progress(current: int, total: int) -> None:
    percent = int(current * 100 / max(total, 1))
    state.progress = percent
    socketio.emit(
        "progress",
        {"current": current, "total": total, "percent": percent},
    )


@socketio.on("connect")
def handle_connect() -> None:  # pragma: no cover - exercised at runtime
    emit_log("Client connected", "info")
    socketio.emit("status", {"connected": True, "logs": state.logs})


@socketio.on("disconnect")
def handle_disconnect() -> None:  # pragma: no cover - exercised at runtime
    emit_log("Client disconnected", "info")


@app.get("/api/health")
def health_check():
    return jsonify(
        {
            "status": "ok",
            "version": "2.0",
            "backend_connected": state.backend is not None,
        }
    )


@app.post("/api/connect")
def connect():
    payload = request.json or {}
    interface = payload.get("interface", "ediabas-dll")
    channel = payload.get("channel", "COM5")
    ecu_type = payload.get("ecu_type", "MSD81")

    emit_log(f"Connecting via {interface} on {channel}")

    args = type("Args", (), {})()
    args.iface = interface
    args.channel = channel
    args.ecu_type = ecu_type
    args.dry_run = False
    args.bitrate = payload.get("bitrate", 500000)
    args.timeout = payload.get("timeout", 1.0)
    args.bt_dll = (
        Path(payload["bt_dll"]) if payload.get("bt_dll") else None
    )
    args.bt_channel = payload.get("bt_channel", 0)

    backend = EdiabasLibBackend(args)
    state.backend = backend
    state.controller = FlashController(backend, ecu_type)

    voltage = backend.read_vbat()
    if voltage is not None:
        emit_log(f"Connected successfully (VBat: {voltage:.1f}V)", "success")
    else:
        emit_log("Connected successfully", "success")
    return jsonify({"success": True, "voltage": voltage, "ecu_type": ecu_type})


@app.post("/api/disconnect")
def disconnect():
    if state.backend:
        state.backend.close()
        state.backend = None
        state.controller = None
    emit_log("Disconnected", "info")
    return jsonify({"success": True})


@app.get("/api/ecu/info")
def ecu_info():
    if not state.controller:
        return jsonify({"success": False, "error": "Not connected"}), 400
    info = state.controller.read_ecu_info()
    return jsonify({"success": True, "info": info})


@app.post("/api/flash/backup")
def backup_flash():
    if not state.controller:
        return jsonify({"success": False, "error": "Not connected"}), 400

    payload = request.json or {}
    target = Path(payload.get("filename", "backup.bin"))

    emit_log(f"Starting backup to {target}")
    state.current_operation = "backup"

    def worker() -> None:
        success = state.controller.backup_flash(target, progress_callback=emit_progress)
        emit_log("Backup complete" if success else "Backup failed", "success" if success else "error")
        state.current_operation = None
        socketio.emit("operation_complete", {"operation": "backup", "success": success})

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"success": True, "message": "Backup started"})


@app.post("/api/flash/upload")
def upload_flash_image():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"success": False, "error": "No file selected"}), 400

    path = Path("/tmp") / uploaded.filename
    uploaded.save(path)

    ecu_type = request.form.get("ecu_type", "MSD81")
    image = FlashImage(path.read_bytes(), ecu_type)
    valid, message = image.validate()
    if not valid:
        return jsonify({"success": False, "error": message}), 400
    return jsonify({"success": True, "message": message, "size": len(image.data), "filename": uploaded.filename})


@app.post("/api/flash/program")
def program_flash():
    if not state.controller:
        return jsonify({"success": False, "error": "Not connected"}), 400

    payload = request.json or {}
    image_path = Path("/tmp") / payload.get("filename", "")
    if not image_path.exists():
        return jsonify({"success": False, "error": "Image not found"}), 400

    ecu_type = payload.get("ecu_type", "MSD81")
    vin = payload.get("vin")

    image_data = image_path.read_bytes()
    image = FlashImage(image_data, ecu_type)
    if vin:
        image_data = image.patch_vin(vin)
        image = FlashImage(image_data, ecu_type)

    emit_log("Starting flash operation", "warning")
    state.current_operation = "flash"

    def worker() -> None:
        success = state.controller.flash_image(image, progress_callback=emit_progress)
        emit_log("Flash completed" if success else "Flash failed", "success" if success else "error")
        state.current_operation = None
        socketio.emit("operation_complete", {"operation": "flash", "success": success})

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"success": True, "message": "Flash started"})


@app.get("/api/maps/list")
def list_maps():
    ecu_type = request.args.get("ecu_type", "MSD81")
    xdf = CommonMaps.create_definition(ecu_type)
    maps = []
    for table in xdf.tables.values():
        maps.append(
            {
                "name": table.name,
                "category": table.category,
                "address": f"0x{table.address:06X}",
                "size": f"{table.rows}x{table.cols}",
                "unit": table.unit,
                "description": table.description,
            }
        )
    return jsonify({"success": True, "maps": maps})


@app.post("/api/maps/read")
def read_map():
    payload = request.json or {}
    map_name = payload.get("map_name")
    flash_file = Path(payload.get("flash_file", ""))
    ecu_type = payload.get("ecu_type", "MSD81")

    if not flash_file.exists():
        return jsonify({"success": False, "error": "Flash file not found"}), 400

    data = flash_file.read_bytes()
    xdf = CommonMaps.create_definition(ecu_type)
    editor = MapEditor(xdf, data)
    table_data = editor.read_table(map_name)
    if table_data is None:
        return jsonify({"success": False, "error": "Map not found"}), 404

    table = xdf.get_table(map_name)
    x_axis = table.x_axis.read_values(data, xdf.endian) if table.x_axis else None
    y_axis = table.y_axis.read_values(data, xdf.endian) if table.y_axis else None

    return jsonify(
        {
            "success": True,
            "data": table_data,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "unit": table.unit,
        }
    )


@app.post("/api/telemetry/start")
def start_telemetry():
    if state.telemetry_session:
        state.telemetry_session.stop()

    series = (request.json or {}).get("series", "E")
    db = BMWSignals.create_database(series)
    session = LiveTelemetrySession(db)

    def forward(point) -> None:
        socketio.emit(
            "telemetry",
            {
                "timestamp": point.timestamp,
                "signals": point.signals,
                "calculated": point.calculated,
            },
        )

    session.add_callback(forward)
    state.telemetry_session = session
    emit_log("Telemetry session started", "success")
    return jsonify({"success": True})


def main() -> None:  # pragma: no cover - manual execution helper
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    LOG.info("Starting simulated flash server on http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":  # pragma: no cover
    main()

