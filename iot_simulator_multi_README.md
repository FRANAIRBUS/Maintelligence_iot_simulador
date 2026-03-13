# Simulador Firebase IoT multi-dispositivo

## Archivos
- `iot_arduino_simulator_multi.py`
- `iot_simulator_multi_config.json` → se crea automáticamente al guardar o cerrar la app

## Dónde guarda la configuración
La app guarda la configuración **en el mismo directorio del script**.

Ruta esperada:
- Si ejecutas el archivo desde `/mnt/data`, guardará en:
  - `/mnt/data/iot_simulator_multi_config.json`

Eso permite:
- copiar el JSON de una máquina a otra
- hacer backup fácilmente
- borrar el archivo para reiniciar toda la configuración

## Qué soporta
- hasta **5 pestañas / dispositivos**
- bootstrap por dispositivo
- sync firmado por HMAC por dispositivo
- auto-sync independiente por pestaña
- termostato + relés + alarmas legacy
- duplicar pestañas para clonar dispositivos
- guardar y recargar configuración

## Uso
```bash
python3 iot_arduino_simulator_multi.py
```

## Flujo recomendado
1. Crear una pestaña por equipo.
2. Rellenar `organizationId`, `deviceKey`, `bootstrapToken`, `bootstrapUrl`.
3. Pulsar `Bootstrap` en cada pestaña.
4. Verificar que se rellenen `deviceSecret`, `syncUrl`, `pollIntervalMs`.
5. Ajustar temperatura, setpoint, relés y demás campos.
6. Usar `Sync ahora` o `Auto-sync`.

## Nota
Si quieres cambiar la ruta del archivo de configuración, puedes modificar en el código la constante:
- `CONFIG_FILENAME`

o la función:
- `config_path()`
