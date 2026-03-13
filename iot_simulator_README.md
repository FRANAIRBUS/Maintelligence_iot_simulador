# Simulador IoT para Mainteligence

## Qué hace
Este script simula un dispositivo tipo Arduino/ESP para la parte IoT de la app:
- hace `bootstrap` contra `iotDeviceBootstrap`
- guarda `deviceSecret`
- envía `reportedState` firmado por HMAC SHA256 a `iotDeviceSync`
- recibe `desiredState`
- puede aplicar automáticamente `setpoint`, `power`, `mode`, `fan` y `relays`
- permite editar campos desde una interfaz Tkinter

## Ejecutar
```bash
python3 iot_arduino_simulator.py
```

## Flujo de prueba
1. En la app abre `/iot`.
2. En el activo IoT pulsa **Provision y control**.
3. Genera el token con **Token generado**.
4. Copia al simulador:
   - `organizationId`
   - `deviceKey`
   - `bootstrapToken`
   - `bootstrapUrl`
5. Pulsa **Bootstrap**.
6. El simulador recibirá:
   - `deviceSecret`
   - `syncUrl`
   - `pollIntervalMs`
7. Ajusta temperatura, humedad, setpoint, relés y demás campos.
8. Pulsa **Sync ahora** o activa **Auto-sync ON**.
9. Desde la app cambia `desiredState` para validar que el simulador lo reciba y lo aplique.

## Campos relevantes que la app acepta
### Bootstrap
```json
{
  "organizationId": "org_demo",
  "deviceKey": "LH-T300-01",
  "bootstrapToken": "token-temporal",
  "firmwareVersion": "1.0.0",
  "capabilities": ["setpoint", "power", "mode", "fan", "relays"]
}
```

### Sync
```json
{
  "reportedState": {
    "readingAt": "2026-03-13T12:00:00.000Z",
    "temperature": 4.2,
    "secondaryTemperature": 5.1,
    "humidity": 81,
    "setpoint": 4.5,
    "power": true,
    "mode": "cool",
    "fan": "auto",
    "status": "online",
    "relays": {"REL1": true, "REL2": false},
    "raw": {"Temp1": "4.2", "Hum1": "81", "Set1": "4.5", "REL1": "1"},
    "firmwareVersion": "1.0.0",
    "ipAddress": "192.168.1.50",
    "uptimeSeconds": 1234,
    "appliedDesiredVersion": 3,
    "applyStatus": "applied",
    "applyMessage": "Aplicado por el simulador"
  },
  "capabilities": ["setpoint", "power", "mode", "fan", "relays"],
  "storeTelemetry": true
}
```

## Notas
- La app **no espera escritura directa a Firestore desde Arduino**; usa las Cloud Functions.
- Los relés pueden enviarse como objeto (`REL1..REL4`) y el `raw` legacy ayuda a que el panel vea compatibilidad con `Temp1`, `Hum1`, `Set1`, `REL1..REL4`, `AL0..AL8`.
- Se guarda configuración local en `simulator_config.json`.
