import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import dataclass, asdict
from pathlib import Path
from tkinter import ttk, messagebox, scrolledtext
from urllib import request, error

APP_TITLE = 'Firebase IoT Simulator - Multi Device'
MAX_DEVICES = 5
CONFIG_FILENAME = 'iot_simulator_multi_config.json'
DEFAULT_HEADERS = {'Content-Type': 'application/json'}


def user_config_dir() -> Path:
    base = os.environ.get('APPDATA') or os.environ.get('LOCALAPPDATA')
    if base:
        p = Path(base) / 'MainteligenceIoTSimulator'
    else:
        p = Path.home() / '.mainteligence_iot_simulator'
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return user_config_dir() / CONFIG_FILENAME


def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def http_json(url: str, payload: dict, timeout: int = 15) -> dict:
    data = json_dumps(payload).encode('utf-8')
    req = request.Request(url, data=data, headers=DEFAULT_HEADERS, method='POST')
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8')
        return json.loads(raw) if raw.strip() else {}


def build_hmac_signature(device_secret: str, timestamp_ms: int, body_bytes: bytes) -> str:
    secret = device_secret.encode('utf-8')
    msg = str(timestamp_ms).encode('utf-8') + b'.' + body_bytes
    digest = hmac.new(secret, msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode('ascii')


@dataclass
class DeviceConfig:
    name: str = 'Dispositivo'
    enabled: bool = True
    organization_id: str = ''
    device_key: str = ''
    bootstrap_token: str = ''
    bootstrap_url: str = ''
    sync_url: str = ''
    device_secret: str = ''
    poll_interval_ms: int = 5000
    auto_sync: bool = False
    auto_apply_desired: bool = True
    temperature: float = 21.5
    humidity: float = 45.0
    setpoint: float = 22.0
    power: bool = True
    mode: str = 'heat'
    fan: str = 'auto'
    status: str = 'online'
    relay1: bool = False
    relay2: bool = False
    relay3: bool = False
    relay4: bool = False
    alarm0: int = 0
    alarm1: int = 0
    alarm2: int = 0
    alarm3: int = 0
    alarm4: int = 0
    alarm5: int = 0
    alarm6: int = 0
    alarm7: int = 0
    alarm8: int = 0
    last_desired_state: str = '{}'


class DeviceTab:
    def __init__(self, app, notebook, index: int, cfg: DeviceConfig):
        self.app = app
        self.index = index
        self.cfg = cfg
        self.frame = ttk.Frame(notebook)
        self.notebook = notebook
        self.auto_sync_job = None
        self.vars = {
            'name': tk.StringVar(value=cfg.name),
            'enabled': tk.BooleanVar(value=cfg.enabled),
            'organization_id': tk.StringVar(value=cfg.organization_id),
            'device_key': tk.StringVar(value=cfg.device_key),
            'bootstrap_token': tk.StringVar(value=cfg.bootstrap_token),
            'bootstrap_url': tk.StringVar(value=cfg.bootstrap_url),
            'sync_url': tk.StringVar(value=cfg.sync_url),
            'device_secret': tk.StringVar(value=cfg.device_secret),
            'poll_interval_ms': tk.IntVar(value=cfg.poll_interval_ms),
            'auto_sync': tk.BooleanVar(value=cfg.auto_sync),
            'auto_apply_desired': tk.BooleanVar(value=cfg.auto_apply_desired),
            'temperature': tk.DoubleVar(value=cfg.temperature),
            'humidity': tk.DoubleVar(value=cfg.humidity),
            'setpoint': tk.DoubleVar(value=cfg.setpoint),
            'power': tk.BooleanVar(value=cfg.power),
            'mode': tk.StringVar(value=cfg.mode),
            'fan': tk.StringVar(value=cfg.fan),
            'status': tk.StringVar(value=cfg.status),
            'relay1': tk.BooleanVar(value=cfg.relay1),
            'relay2': tk.BooleanVar(value=cfg.relay2),
            'relay3': tk.BooleanVar(value=cfg.relay3),
            'relay4': tk.BooleanVar(value=cfg.relay4),
            'alarm0': tk.IntVar(value=cfg.alarm0),
            'alarm1': tk.IntVar(value=cfg.alarm1),
            'alarm2': tk.IntVar(value=cfg.alarm2),
            'alarm3': tk.IntVar(value=cfg.alarm3),
            'alarm4': tk.IntVar(value=cfg.alarm4),
            'alarm5': tk.IntVar(value=cfg.alarm5),
            'alarm6': tk.IntVar(value=cfg.alarm6),
            'alarm7': tk.IntVar(value=cfg.alarm7),
            'alarm8': tk.IntVar(value=cfg.alarm8),
        }
        self._build_ui()
        self._bind_title_updates()
        if self.vars['auto_sync'].get():
            self.schedule_auto_sync()

    def _bind_title_updates(self):
        self.vars['name'].trace_add('write', lambda *_: self.refresh_tab_title())
        self.vars['enabled'].trace_add('write', lambda *_: self.refresh_tab_title())

    def refresh_tab_title(self):
        label = self.vars['name'].get().strip() or f'Device {self.index + 1}'
        if not self.vars['enabled'].get():
            label += ' (off)'
        try:
            self.notebook.tab(self.frame, text=label[:24])
        except tk.TclError:
            pass

    def _build_ui(self):
        root = self.frame
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        top = ttk.LabelFrame(root, text='Identidad y endpoints')
        top.grid(row=0, column=0, sticky='nsew', padx=8, pady=6)
        for i in range(4):
            top.columnconfigure(i, weight=1)
        ttk.Checkbutton(top, text='Activo', variable=self.vars['enabled']).grid(row=0, column=0, sticky='w', padx=4, pady=4)
        ttk.Label(top, text='Nombre').grid(row=0, column=1, sticky='e', padx=4)
        ttk.Entry(top, textvariable=self.vars['name']).grid(row=0, column=2, columnspan=2, sticky='ew', padx=4, pady=4)
        fields = [('Organization ID', 'organization_id'), ('Device Key', 'device_key'), ('Bootstrap Token', 'bootstrap_token'), ('Bootstrap URL', 'bootstrap_url'), ('Sync URL', 'sync_url'), ('Device Secret', 'device_secret'), ('Poll ms', 'poll_interval_ms')]
        for idx, (label, key) in enumerate(fields, start=1):
            ttk.Label(top, text=label).grid(row=idx, column=0, sticky='e', padx=4, pady=2)
            ttk.Entry(top, textvariable=self.vars[key]).grid(row=idx, column=1, columnspan=3, sticky='ew', padx=4, pady=2)

        mid = ttk.Frame(root)
        mid.grid(row=1, column=0, sticky='nsew', padx=8, pady=6)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        thermo = ttk.LabelFrame(mid, text='Termostato')
        thermo.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        for i in range(2):
            thermo.columnconfigure(i, weight=1)
        thermo_fields = [('Temperatura', 'temperature'), ('Humedad', 'humidity'), ('Setpoint', 'setpoint'), ('Modo', 'mode'), ('Ventilador', 'fan'), ('Estado', 'status')]
        for idx, (label, key) in enumerate(thermo_fields):
            ttk.Label(thermo, text=label).grid(row=idx, column=0, sticky='e', padx=4, pady=3)
            ttk.Entry(thermo, textvariable=self.vars[key]).grid(row=idx, column=1, sticky='ew', padx=4, pady=3)
        ttk.Checkbutton(thermo, text='Power ON', variable=self.vars['power']).grid(row=len(thermo_fields), column=0, sticky='w', padx=4, pady=4)
        ttk.Checkbutton(thermo, text='Aplicar desiredState automáticamente', variable=self.vars['auto_apply_desired']).grid(row=len(thermo_fields), column=1, sticky='w', padx=4, pady=4)

        relays = ttk.LabelFrame(mid, text='Relés y alarmas')
        relays.grid(row=0, column=1, sticky='nsew', padx=(4, 0))
        for i in range(6):
            relays.columnconfigure(i, weight=1)
        for idx in range(4):
            ttk.Checkbutton(relays, text=f'REL{idx+1}', variable=self.vars[f'relay{idx+1}']).grid(row=0, column=idx, sticky='w', padx=4, pady=4)
        for idx in range(9):
            ttk.Label(relays, text=f'AL{idx}').grid(row=1 + idx // 3, column=(idx % 3) * 2, sticky='e', padx=4, pady=2)
            ttk.Entry(relays, width=8, textvariable=self.vars[f'alarm{idx}']).grid(row=1 + idx // 3, column=(idx % 3) * 2 + 1, sticky='w', padx=4, pady=2)

        buttons = ttk.Frame(root)
        buttons.grid(row=2, column=0, sticky='ew', padx=8, pady=4)
        for i in range(7):
            buttons.columnconfigure(i, weight=1)
        ttk.Button(buttons, text='Bootstrap', command=self.bootstrap).grid(row=0, column=0, sticky='ew', padx=3)
        ttk.Button(buttons, text='Sync ahora', command=self.sync_now).grid(row=0, column=1, sticky='ew', padx=3)
        ttk.Checkbutton(buttons, text='Auto-sync', variable=self.vars['auto_sync'], command=self.toggle_auto_sync).grid(row=0, column=2, sticky='w', padx=3)
        ttk.Button(buttons, text='Guardar config', command=self.app.save_config).grid(row=0, column=3, sticky='ew', padx=3)
        ttk.Button(buttons, text='Duplicar pestaña', command=self.app.duplicate_current_tab).grid(row=0, column=4, sticky='ew', padx=3)
        ttk.Button(buttons, text='Limpiar', command=self.reset_device).grid(row=0, column=5, sticky='ew', padx=3)
        ttk.Button(buttons, text='Payload preview', command=self.preview_payload).grid(row=0, column=6, sticky='ew', padx=3)

        bottom = ttk.PanedWindow(root, orient='horizontal')
        bottom.grid(row=3, column=0, sticky='nsew', padx=8, pady=(0, 8))
        desired_frame = ttk.LabelFrame(bottom, text='Último desiredState')
        self.desired_text = scrolledtext.ScrolledText(desired_frame, height=12, wrap='word')
        self.desired_text.pack(fill='both', expand=True)
        self.desired_text.insert('1.0', self.cfg.last_desired_state)
        bottom.add(desired_frame, weight=1)
        log_frame = ttk.LabelFrame(bottom, text='Log')
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, wrap='word')
        self.log_text.pack(fill='both', expand=True)
        bottom.add(log_frame, weight=1)
        self.refresh_tab_title()

    def log(self, message: str):
        ts = time.strftime('%H:%M:%S')
        self.log_text.insert('end', f'[{ts}] {message}\n')
        self.log_text.see('end')

    def collect_config(self) -> DeviceConfig:
        desired = self.desired_text.get('1.0', 'end').strip() or '{}'
        return DeviceConfig(
            name=self.vars['name'].get(), enabled=self.vars['enabled'].get(),
            organization_id=self.vars['organization_id'].get().strip(), device_key=self.vars['device_key'].get().strip(),
            bootstrap_token=self.vars['bootstrap_token'].get().strip(), bootstrap_url=self.vars['bootstrap_url'].get().strip(),
            sync_url=self.vars['sync_url'].get().strip(), device_secret=self.vars['device_secret'].get().strip(),
            poll_interval_ms=int(self.vars['poll_interval_ms'].get()), auto_sync=self.vars['auto_sync'].get(),
            auto_apply_desired=self.vars['auto_apply_desired'].get(), temperature=float(self.vars['temperature'].get()),
            humidity=float(self.vars['humidity'].get()), setpoint=float(self.vars['setpoint'].get()), power=self.vars['power'].get(),
            mode=self.vars['mode'].get().strip(), fan=self.vars['fan'].get().strip(), status=self.vars['status'].get().strip(),
            relay1=self.vars['relay1'].get(), relay2=self.vars['relay2'].get(), relay3=self.vars['relay3'].get(), relay4=self.vars['relay4'].get(),
            alarm0=int(self.vars['alarm0'].get()), alarm1=int(self.vars['alarm1'].get()), alarm2=int(self.vars['alarm2'].get()),
            alarm3=int(self.vars['alarm3'].get()), alarm4=int(self.vars['alarm4'].get()), alarm5=int(self.vars['alarm5'].get()),
            alarm6=int(self.vars['alarm6'].get()), alarm7=int(self.vars['alarm7'].get()), alarm8=int(self.vars['alarm8'].get()),
            last_desired_state=desired,
        )

    def apply_config(self, cfg: DeviceConfig):
        for key, var in self.vars.items():
            if hasattr(cfg, key):
                var.set(getattr(cfg, key))
        self.desired_text.delete('1.0', 'end')
        self.desired_text.insert('1.0', cfg.last_desired_state)
        self.refresh_tab_title()
        self.toggle_auto_sync(save=False)

    def reported_state(self):
        return {
            'temperature': round(float(self.vars['temperature'].get()), 2),
            'humidity': round(float(self.vars['humidity'].get()), 2),
            'setpoint': round(float(self.vars['setpoint'].get()), 2),
            'power': bool(self.vars['power'].get()),
            'mode': self.vars['mode'].get().strip(),
            'fan': self.vars['fan'].get().strip(),
            'status': self.vars['status'].get().strip(),
            'relays': {f'REL{i}': bool(self.vars[f'relay{i}'].get()) for i in range(1, 5)},
        }

    def legacy_raw(self):
        return {
            'Temp1': round(float(self.vars['temperature'].get()), 2), 'Hum1': round(float(self.vars['humidity'].get()), 2),
            'Set1': round(float(self.vars['setpoint'].get()), 2), 'Power': 1 if self.vars['power'].get() else 0,
            'Mode': self.vars['mode'].get().strip(), 'Fan': self.vars['fan'].get().strip(), 'Status': self.vars['status'].get().strip(),
            'REL1': 1 if self.vars['relay1'].get() else 0, 'REL2': 1 if self.vars['relay2'].get() else 0,
            'REL3': 1 if self.vars['relay3'].get() else 0, 'REL4': 1 if self.vars['relay4'].get() else 0,
            **{f'AL{i}': int(self.vars[f'alarm{i}'].get()) for i in range(9)},
        }

    def build_sync_payload(self):
        return {'organizationId': self.vars['organization_id'].get().strip(), 'deviceKey': self.vars['device_key'].get().strip(), 'reportedState': self.reported_state(), 'raw': self.legacy_raw(), 'storeTelemetry': True}

    def preview_payload(self):
        self.log(json.dumps(self.build_sync_payload(), ensure_ascii=False, indent=2))

    def bootstrap(self):
        cfg = self.collect_config()
        missing = [name for name, value in [('organizationId', cfg.organization_id), ('deviceKey', cfg.device_key), ('bootstrapToken', cfg.bootstrap_token), ('bootstrapUrl', cfg.bootstrap_url)] if not value]
        if missing:
            messagebox.showerror('Bootstrap', f'Faltan campos: {", ".join(missing)}')
            return
        payload = {'organizationId': cfg.organization_id, 'deviceKey': cfg.device_key, 'bootstrapToken': cfg.bootstrap_token}
        self.log('Enviando bootstrap...')
        threading.Thread(target=self._bootstrap_thread, args=(cfg.bootstrap_url, payload), daemon=True).start()

    def _bootstrap_thread(self, url, payload):
        try:
            data = http_json(url, payload)
            def done():
                if 'deviceSecret' in data:
                    self.vars['device_secret'].set(data.get('deviceSecret', ''))
                if 'syncUrl' in data:
                    self.vars['sync_url'].set(data.get('syncUrl', ''))
                if 'pollIntervalMs' in data:
                    self.vars['poll_interval_ms'].set(int(data.get('pollIntervalMs', 5000)))
                self.log(f'Bootstrap OK: {json.dumps(data, ensure_ascii=False)}')
                self.app.save_config()
            self.frame.after(0, done)
        except error.HTTPError as e:
            body = e.read().decode('utf-8', errors='ignore')
            self.frame.after(0, lambda: self.log(f'Bootstrap HTTP {e.code}: {body}'))
        except Exception as e:
            self.frame.after(0, lambda: self.log(f'Bootstrap error: {e}'))

    def sync_now(self):
        cfg = self.collect_config()
        missing = [name for name, value in [('organizationId', cfg.organization_id), ('deviceKey', cfg.device_key), ('syncUrl', cfg.sync_url), ('deviceSecret', cfg.device_secret)] if not value]
        if missing:
            messagebox.showerror('Sync', f'Faltan campos: {", ".join(missing)}')
            return
        payload = self.build_sync_payload()
        self.log('Enviando sync...')
        threading.Thread(target=self._sync_thread, args=(cfg.sync_url, cfg.device_secret, payload), daemon=True).start()

    def _sync_thread(self, url, device_secret, payload):
        try:
            body = json_dumps(payload).encode('utf-8')
            ts = int(time.time() * 1000)
            sig = build_hmac_signature(device_secret, ts, body)
            req = request.Request(url, data=body, headers={'Content-Type': 'application/json', 'X-IOT-TIMESTAMP': str(ts), 'X-IOT-SIGNATURE': sig}, method='POST')
            with request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode('utf-8')
                data = json.loads(raw) if raw.strip() else {}
            self.frame.after(0, lambda: self._handle_sync_response(data))
        except error.HTTPError as e:
            body = e.read().decode('utf-8', errors='ignore')
            self.frame.after(0, lambda: self.log(f'Sync HTTP {e.code}: {body}'))
        except Exception as e:
            self.frame.after(0, lambda: self.log(f'Sync error: {e}'))

    def _handle_sync_response(self, data: dict):
        self.log(f'Sync OK: {json.dumps(data, ensure_ascii=False, indent=2)}')
        desired = data.get('desiredState', {})
        self.desired_text.delete('1.0', 'end')
        self.desired_text.insert('1.0', json.dumps(desired, ensure_ascii=False, indent=2))
        if self.vars['auto_apply_desired'].get() and desired:
            self.apply_desired_state(desired)
        self.app.save_config()

    def apply_desired_state(self, desired: dict):
        if 'setpoint' in desired:
            self.vars['setpoint'].set(desired['setpoint'])
        if 'power' in desired:
            self.vars['power'].set(bool(desired['power']))
        if 'mode' in desired:
            self.vars['mode'].set(str(desired['mode']))
        if 'fan' in desired:
            self.vars['fan'].set(str(desired['fan']))
        if 'status' in desired:
            self.vars['status'].set(str(desired['status']))
        relays = desired.get('relays', {})
        if isinstance(relays, dict):
            for idx in range(1, 5):
                key = f'REL{idx}'
                if key in relays:
                    self.vars[f'relay{idx}'].set(bool(relays[key]))
        self.log('desiredState aplicado al simulador.')

    def schedule_auto_sync(self):
        self.cancel_auto_sync()
        if not self.vars['auto_sync'].get():
            return
        interval = max(1000, int(self.vars['poll_interval_ms'].get()))
        self.auto_sync_job = self.frame.after(interval, self._auto_sync_tick)

    def _auto_sync_tick(self):
        self.auto_sync_job = None
        if self.vars['enabled'].get() and self.vars['auto_sync'].get():
            self.sync_now()
        self.schedule_auto_sync()

    def cancel_auto_sync(self):
        if self.auto_sync_job is not None:
            self.frame.after_cancel(self.auto_sync_job)
            self.auto_sync_job = None

    def toggle_auto_sync(self, save=True):
        if self.vars['auto_sync'].get():
            self.log('Auto-sync activado.')
            self.schedule_auto_sync()
        else:
            self.log('Auto-sync desactivado.')
            self.cancel_auto_sync()
        if save:
            self.app.save_config()

    def reset_device(self):
        self.apply_config(DeviceConfig(name=f'Device {self.index + 1}'))
        self.log('Pestaña reiniciada.')
        self.app.save_config()


class SimulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry('1400x900')
        self.tabs = []
        topbar = ttk.Frame(root)
        topbar.pack(fill='x', padx=8, pady=6)
        ttk.Button(topbar, text='Guardar todo', command=self.save_config).pack(side='left', padx=4)
        ttk.Button(topbar, text='Cargar config', command=self.reload_config).pack(side='left', padx=4)
        ttk.Button(topbar, text='Añadir pestaña', command=self.add_tab).pack(side='left', padx=4)
        ttk.Button(topbar, text='Duplicar actual', command=self.duplicate_current_tab).pack(side='left', padx=4)
        ttk.Button(topbar, text='Eliminar actual', command=self.remove_current_tab).pack(side='left', padx=4)
        ttk.Label(topbar, text=f'Config: {config_path()}').pack(side='right', padx=4)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)
        self.load_config()
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    def default_configs(self):
        return [DeviceConfig(name=f'Device {i+1}') for i in range(2)]

    def load_config(self):
        path = config_path()
        configs = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                for item in data.get('devices', [])[:MAX_DEVICES]:
                    configs.append(DeviceConfig(**item))
            except Exception:
                configs = []
        if not configs:
            configs = self.default_configs()
        for tab in self.tabs:
            tab.cancel_auto_sync()
            self.notebook.forget(tab.frame)
        self.tabs.clear()
        for cfg in configs:
            self._create_tab(cfg)
        if not self.tabs:
            self._create_tab(DeviceConfig(name='Device 1'))

    def reload_config(self):
        self.load_config()
        messagebox.showinfo('Configuración', f'Configuración recargada desde:\n{config_path()}')

    def _create_tab(self, cfg: DeviceConfig):
        tab = DeviceTab(self, self.notebook, len(self.tabs), cfg)
        self.tabs.append(tab)
        self.notebook.add(tab.frame, text=cfg.name)
        tab.refresh_tab_title()

    def add_tab(self):
        if len(self.tabs) >= MAX_DEVICES:
            messagebox.showwarning('Límite', f'Solo se permiten {MAX_DEVICES} pestañas.')
            return
        self._create_tab(DeviceConfig(name=f'Device {len(self.tabs) + 1}'))
        self.notebook.select(self.tabs[-1].frame)
        self.save_config()

    def current_tab(self):
        current = self.notebook.select()
        for tab in self.tabs:
            if str(tab.frame) == current:
                return tab
        return self.tabs[0] if self.tabs else None

    def duplicate_current_tab(self):
        tab = self.current_tab()
        if tab is None:
            return
        if len(self.tabs) >= MAX_DEVICES:
            messagebox.showwarning('Límite', f'Solo se permiten {MAX_DEVICES} pestañas.')
            return
        cfg = tab.collect_config()
        cfg.name = f'{cfg.name} copia'
        self._create_tab(cfg)
        self.notebook.select(self.tabs[-1].frame)
        self.save_config()

    def remove_current_tab(self):
        if len(self.tabs) <= 1:
            messagebox.showwarning('Pestañas', 'Debe quedar al menos una pestaña.')
            return
        tab = self.current_tab()
        if tab is None:
            return
        tab.cancel_auto_sync()
        idx = self.tabs.index(tab)
        self.notebook.forget(tab.frame)
        self.tabs.pop(idx)
        for i, t in enumerate(self.tabs):
            t.index = i
            t.refresh_tab_title()
        self.save_config()

    def save_config(self):
        path = config_path()
        data = {'devices': [asdict(tab.collect_config()) for tab in self.tabs], 'savedAt': int(time.time()), 'maxDevices': MAX_DEVICES}
        try:
            fd, tmp_name = tempfile.mkstemp(prefix='iotmulti_', suffix='.json', dir=str(path.parent))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            current = self.current_tab()
            if current:
                current.log(f'Configuración guardada en {path}')
            return True
        except Exception as e:
            current = self.current_tab()
            if current:
                current.log(f'Error guardando configuración: {e}')
            try:
                messagebox.showerror('Guardar configuración', f'{path}\n{e}')
            except Exception:
                pass
            return False

    def on_close(self):
        self.save_config()
        for tab in self.tabs:
            tab.cancel_auto_sync()
        self.root.destroy()


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except Exception:
        pass
    SimulatorApp(root)
    root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        try:
            messagebox.showerror('Error al iniciar', f'{type(e).__name__}: {e}')
        except Exception:
            print(f'{type(e).__name__}: {e}', file=sys.stderr)
        raise
