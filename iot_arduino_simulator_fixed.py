#!/usr/bin/env python3
"""
Simulador de dispositivo IoT para Mainteligence.

Cambios principales:
- La configuración se guarda por defecto en el mismo directorio del .py
- Soporte multidispositivo con hasta 5 pestañas superiores
- Cada dispositivo tiene su propia configuración independiente
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "simulator_config.json"
MAX_DEVICES = 5

DEFAULT_CAPABILITIES = ["setpoint", "power", "mode", "fan", "relays"]
DEFAULT_RELAYS = {"REL1": False, "REL2": False, "REL3": False, "REL4": False}


@dataclass
class SimulatorConfig:
    organizationId: str = "org_demo"
    deviceKey: str = "LH-T300-01"
    bootstrapToken: str = ""
    bootstrapUrl: str = ""
    syncUrl: str = ""
    deviceSecret: str = ""
    firmwareVersion: str = "1.0.0"
    pollIntervalMs: int = 15000
    capabilities: List[str] = field(default_factory=lambda: DEFAULT_CAPABILITIES.copy())
    storeTelemetry: bool = True
    autoApplyDesired: bool = True
    readingAtFromNow: bool = True
    useCustomRaw: bool = False
    rawJsonText: str = "{}"
    state: Dict[str, Any] = field(default_factory=lambda: {
        "temperature": 4.2,
        "secondaryTemperature": "",
        "humidity": 81,
        "setpoint": 4.5,
        "power": True,
        "mode": "cool",
        "fan": "auto",
        "status": "online",
        "ipAddress": "192.168.1.50",
        "uptimeSeconds": 0,
        "applyStatus": "idle",
        "applyMessage": "",
        "appliedDesiredVersion": "",
        "alarms": [],
        "relays": DEFAULT_RELAYS.copy(),
    })


class MaintIoTSimulator:
    def __init__(self, config: SimulatorConfig):
        self.config = config
        self.last_desired_state: Optional[Dict[str, Any]] = None
        self.last_sync_response: Optional[Dict[str, Any]] = None
        self.auto_sync_running = False
        self.auto_sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def bootstrap(self) -> Dict[str, Any]:
        payload = {
            "organizationId": self.config.organizationId,
            "deviceKey": self.config.deviceKey,
            "bootstrapToken": self.config.bootstrapToken,
            "firmwareVersion": self.config.firmwareVersion,
            "capabilities": self.config.capabilities,
        }
        response = http_json("POST", self.config.bootstrapUrl, payload, headers={})
        self.config.deviceSecret = str(response.get("deviceSecret") or "")
        if response.get("syncUrl"):
            self.config.syncUrl = str(response["syncUrl"])
        if response.get("pollIntervalMs"):
            self.config.pollIntervalMs = int(response["pollIntervalMs"])
        return response

    def build_reported_state(self) -> Dict[str, Any]:
        s = self.config.state
        relays = {
            label.upper(): bool(active)
            for label, active in (s.get("relays") or {}).items()
        }
        raw = self._build_raw(relays)
        reported: Dict[str, Any] = {
            "readingAt": iso_now() if self.config.readingAtFromNow else None,
            "temperature": parse_optional_number(s.get("temperature")),
            "secondaryTemperature": parse_optional_number(s.get("secondaryTemperature")),
            "humidity": parse_optional_number(s.get("humidity")),
            "setpoint": parse_optional_number(s.get("setpoint")),
            "power": bool(s.get("power")),
            "mode": str(s.get("mode") or "").strip() or None,
            "fan": str(s.get("fan") or "").strip() or None,
            "status": str(s.get("status") or "").strip() or None,
            "alarms": [a for a in (s.get("alarms") or []) if str(a).strip()],
            "relays": relays,
            "raw": raw,
            "firmwareVersion": str(self.config.firmwareVersion or "").strip() or None,
            "ipAddress": str(s.get("ipAddress") or "").strip() or None,
            "uptimeSeconds": int(parse_optional_number(s.get("uptimeSeconds")) or 0),
            "appliedDesiredVersion": parse_optional_number(s.get("appliedDesiredVersion")),
            "applyStatus": str(s.get("applyStatus") or "").strip() or None,
            "applyMessage": str(s.get("applyMessage") or "").strip() or None,
        }
        return {k: v for k, v in reported.items() if v is not None}

    def _build_raw(self, relays: Dict[str, bool]) -> Dict[str, Any]:
        if self.config.useCustomRaw:
            try:
                parsed = json.loads(self.config.rawJsonText or "{}")
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        state = self.config.state
        raw: Dict[str, Any] = {}
        mapping = {
            "Temp1": state.get("temperature"),
            "Temp2": state.get("secondaryTemperature"),
            "Hum1": state.get("humidity"),
            "Set1": state.get("setpoint"),
        }
        for key, value in mapping.items():
            if value not in (None, ""):
                raw[key] = str(value)
        for label, active in relays.items():
            raw[label] = "1" if active else "0"
        alarms = state.get("alarms") or []
        for idx, alarm in enumerate(alarms[:9]):
            if str(alarm).strip():
                raw[f"AL{idx}"] = str(alarm)
        return raw

    def sync_once(self) -> Dict[str, Any]:
        if not self.config.deviceSecret:
            raise ValueError("Falta deviceSecret. Primero ejecuta Bootstrap o pega el deviceSecret manualmente.")
        if not self.config.syncUrl:
            raise ValueError("Falta syncUrl.")
        body = {
            "reportedState": self.build_reported_state(),
            "capabilities": self.config.capabilities,
            "storeTelemetry": bool(self.config.storeTelemetry),
        }
        raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        ts = str(int(time.time() * 1000))
        signature = hmac.new(
            self.config.deviceSecret.encode("utf-8"),
            f"{ts}.{raw_body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "x-maint-org-id": self.config.organizationId,
            "x-maint-device-key": self.config.deviceKey,
            "x-maint-ts": ts,
            "x-maint-signature": signature,
        }
        response = http_raw_json("POST", self.config.syncUrl, raw_body, headers=headers)
        self.last_sync_response = response
        self.last_desired_state = response.get("desiredState") if isinstance(response, dict) else None
        if self.config.autoApplyDesired and isinstance(self.last_desired_state, dict):
            self.apply_desired_state(self.last_desired_state)
        self._tick_uptime()
        if response.get("pollIntervalMs"):
            self.config.pollIntervalMs = int(response["pollIntervalMs"])
        return response

    def _tick_uptime(self) -> None:
        current = parse_optional_number(self.config.state.get("uptimeSeconds")) or 0
        interval_seconds = max(int(self.config.pollIntervalMs / 1000), 1)
        self.config.state["uptimeSeconds"] = int(current) + interval_seconds

    def apply_desired_state(self, desired: Dict[str, Any]) -> None:
        state = self.config.state
        changed: List[str] = []
        if "setpoint" in desired and desired["setpoint"] not in (None, ""):
            state["setpoint"] = desired["setpoint"]
            changed.append("setpoint")
        if "power" in desired and desired["power"] is not None:
            state["power"] = bool(desired["power"])
            changed.append("power")
        if "mode" in desired and desired["mode"] not in (None, ""):
            state["mode"] = desired["mode"]
            changed.append("mode")
        if "fan" in desired and desired["fan"] not in (None, ""):
            state["fan"] = desired["fan"]
            changed.append("fan")
        if isinstance(desired.get("relays"), dict):
            relay_map = state.setdefault("relays", DEFAULT_RELAYS.copy())
            for label, active in desired["relays"].items():
                relay_map[str(label).upper()] = bool(active)
                changed.append(f"relay:{str(label).upper()}")
        version = desired.get("version")
        if version not in (None, ""):
            state["appliedDesiredVersion"] = int(version)
        state["applyStatus"] = "applied"
        state["applyMessage"] = "Aplicado por el simulador"
        if not changed:
            state["applyStatus"] = "idle"
            state["applyMessage"] = "No había cambios aplicables"

    def start_auto_sync(self, callback) -> None:
        if self.auto_sync_running:
            return
        self.auto_sync_running = True
        self._stop_event.clear()

        def runner():
            while not self._stop_event.is_set():
                try:
                    result = self.sync_once()
                    callback("sync_ok", result)
                except Exception as exc:
                    callback("sync_error", str(exc))
                wait_seconds = max(self.config.pollIntervalMs / 1000.0, 1.0)
                self._stop_event.wait(wait_seconds)

        self.auto_sync_thread = threading.Thread(target=runner, daemon=True)
        self.auto_sync_thread.start()

    def stop_auto_sync(self) -> None:
        self.auto_sync_running = False
        self._stop_event.set()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_optional_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    return float(text)


def http_json(method: str, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json; charset=utf-8", **headers}
    req = Request(url=url, data=body, headers=req_headers, method=method.upper())
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Error de red: {exc}") from exc


def http_raw_json(method: str, url: str, raw_body: str, headers: Dict[str, str]) -> Dict[str, Any]:
    req = Request(url=url, data=raw_body.encode("utf-8"), headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Error de red: {exc}") from exc


def _normalize_config(cfg: SimulatorConfig) -> SimulatorConfig:
    if not isinstance(cfg.state.get("relays"), dict):
        cfg.state["relays"] = DEFAULT_RELAYS.copy()
    else:
        merged_relays = DEFAULT_RELAYS.copy()
        merged_relays.update({str(k).upper(): bool(v) for k, v in cfg.state["relays"].items()})
        cfg.state["relays"] = merged_relays
    if not isinstance(cfg.capabilities, list):
        cfg.capabilities = DEFAULT_CAPABILITIES.copy()
    return cfg


def load_config(path: Path = CONFIG_PATH) -> SimulatorConfig:
    if not path.exists():
        return SimulatorConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    cfg = SimulatorConfig()
    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return _normalize_config(cfg)


def save_config(config: SimulatorConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


def load_all_configs(path: Path = CONFIG_PATH, count: int = MAX_DEVICES) -> List[SimulatorConfig]:
    if not path.exists():
        return [SimulatorConfig(deviceKey=f"LH-T300-{idx+1:02d}") for idx in range(count)]

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict) and "devices" in data:
        items = data.get("devices") or []
        configs: List[SimulatorConfig] = []
        for idx in range(count):
            raw = items[idx] if idx < len(items) and isinstance(items[idx], dict) else {}
            cfg = SimulatorConfig(deviceKey=f"LH-T300-{idx+1:02d}")
            for key, value in raw.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
            configs.append(_normalize_config(cfg))
        return configs

    legacy = load_config(path)
    configs = [legacy]
    for idx in range(1, count):
        configs.append(SimulatorConfig(deviceKey=f"LH-T300-{idx+1:02d}"))
    return configs


def save_all_configs(configs: List[SimulatorConfig], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "savedAt": iso_now(),
        "devices": [asdict(cfg) for cfg in configs[:MAX_DEVICES]],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class DevicePanel(ttk.Frame):
    def __init__(self, parent, config_data: SimulatorConfig, device_index: int, save_callback):
        super().__init__(parent)
        self.config_data = config_data
        self.device_index = device_index
        self.save_callback = save_callback
        self.sim = MaintIoTSimulator(self.config_data)
        self.vars: Dict[str, tk.Variable] = {}
        self.relay_vars: Dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self._load_to_ui()

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_conn = ttk.Frame(notebook)
        self.tab_state = ttk.Frame(notebook)
        self.tab_log = ttk.Frame(notebook)
        notebook.add(self.tab_conn, text="Conexión")
        notebook.add(self.tab_state, text="Estado / Relés")
        notebook.add(self.tab_log, text="desiredState / Log")

        self._build_connection_tab()
        self._build_state_tab()
        self._build_log_tab()

    def _build_connection_tab(self):
        frm = ttk.Frame(self.tab_conn, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        fields = [
            ("organizationId", "Organization ID"),
            ("deviceKey", "Device Key"),
            ("bootstrapToken", "Bootstrap Token"),
            ("bootstrapUrl", "Bootstrap URL"),
            ("syncUrl", "Sync URL"),
            ("deviceSecret", "Device Secret"),
            ("firmwareVersion", "Firmware Version"),
            ("pollIntervalMs", "Poll Interval (ms)"),
            ("capabilities", "Capabilities (csv)"),
        ]
        for row, (key, label) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            if key in {"bootstrapToken", "deviceSecret"}:
                entry = ttk.Entry(frm, textvariable=var, show="*")
            else:
                entry = ttk.Entry(frm, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 0))
            self.vars[key] = var

        self.vars["storeTelemetry"] = tk.BooleanVar()
        self.vars["autoApplyDesired"] = tk.BooleanVar()
        self.vars["readingAtFromNow"] = tk.BooleanVar()
        ttk.Checkbutton(frm, text="Guardar telemetría histórica", variable=self.vars["storeTelemetry"]).grid(row=9, column=0, sticky="w", pady=(12, 4))
        ttk.Checkbutton(frm, text="Aplicar desiredState automáticamente", variable=self.vars["autoApplyDesired"]).grid(row=9, column=1, sticky="w", pady=(12, 4))
        ttk.Checkbutton(frm, text="Usar readingAt = ahora", variable=self.vars["readingAtFromNow"]).grid(row=10, column=0, sticky="w", pady=4)

        btns = ttk.Frame(frm)
        btns.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(16, 8))
        for i in range(7):
            btns.columnconfigure(i, weight=1)
        ttk.Button(btns, text="Bootstrap", command=self.do_bootstrap).grid(row=0, column=0, padx=4, sticky="ew")
        ttk.Button(btns, text="Sync ahora", command=self.do_sync).grid(row=0, column=1, padx=4, sticky="ew")
        ttk.Button(btns, text="Auto-sync ON", command=self.start_auto_sync).grid(row=0, column=2, padx=4, sticky="ew")
        ttk.Button(btns, text="Auto-sync OFF", command=self.stop_auto_sync).grid(row=0, column=3, padx=4, sticky="ew")
        ttk.Button(btns, text="Guardar config", command=self.save_current_config).grid(row=0, column=4, padx=4, sticky="ew")
        ttk.Button(btns, text="Exportar JSON", command=self.export_config).grid(row=0, column=5, padx=4, sticky="ew")
        ttk.Button(btns, text="Importar JSON", command=self.import_config).grid(row=0, column=6, padx=4, sticky="ew")

        hint = (
            f"Dispositivo {self.device_index + 1}. La configuración general se guarda en: {CONFIG_PATH}. "
            "Cada pestaña superior mantiene su propio deviceKey, secretos y estado."
        )
        ttk.Label(frm, text=hint, wraplength=1000, foreground="#555").grid(row=12, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_state_tab(self):
        frm = ttk.Frame(self.tab_state, padding=12)
        frm.pack(fill="both", expand=True)

        left = ttk.LabelFrame(frm, text="reportedState", padding=10)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = ttk.LabelFrame(frm, text="raw / relés / alarmas", padding=10)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        left.columnconfigure(1, weight=1)
        state_fields = [
            ("temperature", "Temperature"),
            ("secondaryTemperature", "Secondary Temp"),
            ("humidity", "Humidity"),
            ("setpoint", "Setpoint"),
            ("mode", "Mode"),
            ("fan", "Fan"),
            ("status", "Status"),
            ("ipAddress", "IP Address"),
            ("uptimeSeconds", "Uptime Seconds"),
            ("applyStatus", "Apply Status"),
            ("applyMessage", "Apply Message"),
            ("appliedDesiredVersion", "Applied Desired Version"),
        ]
        for row, (key, label) in enumerate(state_fields):
            ttk.Label(left, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar()
            ttk.Entry(left, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 0))
            self.vars[key] = var

        self.vars["power"] = tk.BooleanVar()
        ttk.Checkbutton(left, text="Power", variable=self.vars["power"]).grid(row=len(state_fields), column=0, sticky="w", pady=(8, 4))

        right.columnconfigure(0, weight=1)
        relay_frame = ttk.LabelFrame(right, text="Relés")
        relay_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for idx, label in enumerate(["REL1", "REL2", "REL3", "REL4"]):
            var = tk.BooleanVar()
            self.relay_vars[label] = var
            ttk.Checkbutton(relay_frame, text=label, variable=var).grid(row=0, column=idx, padx=8, pady=8, sticky="w")

        ttk.Label(right, text="Alarmas (una por línea)").grid(row=1, column=0, sticky="w")
        self.alarms_text = tk.Text(right, height=8)
        self.alarms_text.grid(row=2, column=0, sticky="nsew", pady=(4, 8))

        self.vars["useCustomRaw"] = tk.BooleanVar()
        ttk.Checkbutton(right, text="Usar raw JSON personalizado", variable=self.vars["useCustomRaw"]).grid(row=3, column=0, sticky="w", pady=(0, 4))
        ttk.Label(right, text="raw JSON personalizado").grid(row=4, column=0, sticky="w")
        self.raw_text = tk.Text(right, height=12)
        self.raw_text.grid(row=5, column=0, sticky="nsew", pady=(4, 8))
        right.rowconfigure(5, weight=1)

        ttk.Button(right, text="Aplicar desiredState recibido", command=self.apply_desired_from_text).grid(row=6, column=0, sticky="ew", pady=6)
        ttk.Button(right, text="Ver reportedState JSON", command=self.show_reported_state_preview).grid(row=7, column=0, sticky="ew")

    def _build_log_tab(self):
        frm = ttk.Frame(self.tab_log, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)

        ttk.Label(frm, text="desiredState recibido").grid(row=0, column=0, sticky="w")
        self.desired_text = tk.Text(frm, height=12)
        self.desired_text.grid(row=1, column=0, sticky="nsew", pady=(4, 10))

        ttk.Label(frm, text="Log").grid(row=2, column=0, sticky="w")
        self.log_text = tk.Text(frm, height=18)
        self.log_text.grid(row=3, column=0, sticky="nsew", pady=(4, 0))

    def _load_to_ui(self):
        cfg = self.config_data
        self.vars["organizationId"].set(cfg.organizationId)
        self.vars["deviceKey"].set(cfg.deviceKey)
        self.vars["bootstrapToken"].set(cfg.bootstrapToken)
        self.vars["bootstrapUrl"].set(cfg.bootstrapUrl)
        self.vars["syncUrl"].set(cfg.syncUrl)
        self.vars["deviceSecret"].set(cfg.deviceSecret)
        self.vars["firmwareVersion"].set(cfg.firmwareVersion)
        self.vars["pollIntervalMs"].set(str(cfg.pollIntervalMs))
        self.vars["capabilities"].set(", ".join(cfg.capabilities))
        self.vars["storeTelemetry"].set(cfg.storeTelemetry)
        self.vars["autoApplyDesired"].set(cfg.autoApplyDesired)
        self.vars["readingAtFromNow"].set(cfg.readingAtFromNow)
        self.vars["useCustomRaw"].set(cfg.useCustomRaw)

        state = cfg.state
        for key in [
            "temperature", "secondaryTemperature", "humidity", "setpoint", "mode", "fan", "status",
            "ipAddress", "uptimeSeconds", "applyStatus", "applyMessage", "appliedDesiredVersion"
        ]:
            self.vars[key].set("" if state.get(key) is None else str(state.get(key)))
        self.vars["power"].set(bool(state.get("power")))
        for label, var in self.relay_vars.items():
            var.set(bool((state.get("relays") or {}).get(label)))

        self.alarms_text.delete("1.0", "end")
        self.alarms_text.insert("1.0", "\n".join(state.get("alarms") or []))
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", cfg.rawJsonText or "{}")
        self.desired_text.delete("1.0", "end")
        if self.sim.last_desired_state:
            self.desired_text.insert("1.0", json.dumps(self.sim.last_desired_state, indent=2, ensure_ascii=False))

    def _save_from_ui(self):
        cfg = self.config_data
        cfg.organizationId = self.vars["organizationId"].get().strip()
        cfg.deviceKey = self.vars["deviceKey"].get().strip().upper().replace(" ", "-")
        cfg.bootstrapToken = self.vars["bootstrapToken"].get().strip()
        cfg.bootstrapUrl = self.vars["bootstrapUrl"].get().strip()
        cfg.syncUrl = self.vars["syncUrl"].get().strip()
        cfg.deviceSecret = self.vars["deviceSecret"].get().strip()
        cfg.firmwareVersion = self.vars["firmwareVersion"].get().strip()
        cfg.pollIntervalMs = int(self.vars["pollIntervalMs"].get().strip() or "15000")
        cfg.capabilities = [item.strip() for item in self.vars["capabilities"].get().split(",") if item.strip()]
        cfg.storeTelemetry = bool(self.vars["storeTelemetry"].get())
        cfg.autoApplyDesired = bool(self.vars["autoApplyDesired"].get())
        cfg.readingAtFromNow = bool(self.vars["readingAtFromNow"].get())
        cfg.useCustomRaw = bool(self.vars["useCustomRaw"].get())
        cfg.rawJsonText = self.raw_text.get("1.0", "end").strip() or "{}"

        cfg.state.update({
            "temperature": self.vars["temperature"].get().strip(),
            "secondaryTemperature": self.vars["secondaryTemperature"].get().strip(),
            "humidity": self.vars["humidity"].get().strip(),
            "setpoint": self.vars["setpoint"].get().strip(),
            "mode": self.vars["mode"].get().strip(),
            "fan": self.vars["fan"].get().strip(),
            "status": self.vars["status"].get().strip(),
            "ipAddress": self.vars["ipAddress"].get().strip(),
            "uptimeSeconds": self.vars["uptimeSeconds"].get().strip(),
            "applyStatus": self.vars["applyStatus"].get().strip(),
            "applyMessage": self.vars["applyMessage"].get().strip(),
            "appliedDesiredVersion": self.vars["appliedDesiredVersion"].get().strip(),
            "power": bool(self.vars["power"].get()),
            "relays": {label: bool(var.get()) for label, var in self.relay_vars.items()},
            "alarms": [line.strip() for line in self.alarms_text.get("1.0", "end").splitlines() if line.strip()],
        })

    def log(self, message: str, payload: Optional[Any] = None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        if payload is not None:
            if isinstance(payload, str):
                self.log_text.insert("end", payload + "\n")
            else:
                self.log_text.insert("end", json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        self.log_text.insert("end", "\n")
        self.log_text.see("end")

    def set_desired_text(self, data: Any):
        self.desired_text.delete("1.0", "end")
        self.desired_text.insert("1.0", json.dumps(data, indent=2, ensure_ascii=False))

    def do_bootstrap(self):
        self._save_from_ui()
        try:
            result = self.sim.bootstrap()
            self.vars["deviceSecret"].set(self.config_data.deviceSecret)
            self.vars["syncUrl"].set(self.config_data.syncUrl)
            self.vars["pollIntervalMs"].set(str(self.config_data.pollIntervalMs))
            self.log("Bootstrap OK", result)
            self.save_callback()
        except Exception as exc:
            self.log("Bootstrap ERROR", str(exc))
            messagebox.showerror("Bootstrap", str(exc))

    def do_sync(self):
        self._save_from_ui()
        try:
            result = self.sim.sync_once()
            desired = result.get("desiredState") if isinstance(result, dict) else None
            if desired is not None:
                self.set_desired_text(desired)
            self._load_to_ui()
            self.log("Sync OK", result)
            self.save_callback()
        except Exception as exc:
            self.log("Sync ERROR", str(exc))
            messagebox.showerror("Sync", str(exc))

    def start_auto_sync(self):
        self._save_from_ui()

        def callback(kind: str, payload: Any):
            self.after(0, lambda: self._handle_async_event(kind, payload))

        self.sim.start_auto_sync(callback)
        self.log("Auto-sync iniciado")

    def _handle_async_event(self, kind: str, payload: Any):
        if kind == "sync_ok":
            desired = payload.get("desiredState") if isinstance(payload, dict) else None
            if desired is not None:
                self.set_desired_text(desired)
            self._load_to_ui()
            self.log("Auto-sync OK", payload)
            self.save_callback()
        else:
            self.log("Auto-sync ERROR", payload)

    def stop_auto_sync(self):
        self.sim.stop_auto_sync()
        self.log("Auto-sync detenido")

    def save_current_config(self):
        self._save_from_ui()
        self.save_callback()
        self.log(f"Config del dispositivo guardada en {CONFIG_PATH}")

    def export_config(self):
        self._save_from_ui()
        default_name = f"simulator_device_{self.device_index + 1}.json"
        target = filedialog.asksaveasfilename(
            initialdir=str(BASE_DIR),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not target:
            return
        save_config(self.config_data, Path(target))
        self.log(f"Config exportada a {target}")

    def import_config(self):
        target = filedialog.askopenfilename(
            initialdir=str(BASE_DIR),
            filetypes=[("JSON", "*.json")],
        )
        if not target:
            return
        self.stop_auto_sync()
        self.config_data = load_config(Path(target))
        self.sim = MaintIoTSimulator(self.config_data)
        self._load_to_ui()
        self.save_callback()
        self.log(f"Config importada desde {target}")

    def show_reported_state_preview(self):
        self._save_from_ui()
        preview = self.sim.build_reported_state()
        messagebox.showinfo("reportedState preview", json.dumps(preview, indent=2, ensure_ascii=False))
        self.log("Preview reportedState", preview)

    def apply_desired_from_text(self):
        try:
            data = json.loads(self.desired_text.get("1.0", "end").strip() or "{}")
            if not isinstance(data, dict):
                raise ValueError("desiredState debe ser un objeto JSON")
            self._save_from_ui()
            self.sim.apply_desired_state(data)
            self._load_to_ui()
            self.log("desiredState aplicado manualmente", data)
            self.save_callback()
        except Exception as exc:
            self.log("Error aplicando desiredState", str(exc))
            messagebox.showerror("desiredState", str(exc))

    def shutdown(self):
        self.stop_auto_sync()
        self._save_from_ui()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mainteligence IoT Simulator")
        self.geometry("1320x900")
        self.minsize(1080, 760)

        self.configs = load_all_configs()
        self.device_tabs: List[DevicePanel] = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        top_bar = ttk.Frame(self, padding=(10, 10, 10, 0))
        top_bar.pack(fill="x")

        ttk.Label(
            top_bar,
            text=f"Archivo de configuración: {CONFIG_PATH}",
            foreground="#555",
        ).pack(side="left")

        ttk.Button(top_bar, text="Guardar todo", command=self.save_all).pack(side="right", padx=(8, 0))

        self.devices_notebook = ttk.Notebook(self)
        self.devices_notebook.pack(fill="both", expand=True, padx=10, pady=10)

        for idx in range(MAX_DEVICES):
            config = self.configs[idx]
            panel = DevicePanel(
                self.devices_notebook,
                config_data=config,
                device_index=idx,
                save_callback=self.save_all,
            )
            self.device_tabs.append(panel)
            self.devices_notebook.add(panel, text=f"Dispositivo {idx + 1}")

    def save_all(self):
        for panel in self.device_tabs:
            panel._save_from_ui()
        save_all_configs([panel.config_data for panel in self.device_tabs], CONFIG_PATH)

    def on_close(self):
        for panel in self.device_tabs:
            panel.shutdown()
        self.save_all()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
