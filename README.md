# EGLO connect.z Fernbedienung 2.0 for Home Assistant (ZHA)

Native [ZHA](https://www.home-assistant.io/integrations/zha/) support for the
**EGLO connect.z Smart Home Fernbedienung 2.0** (AwoX `ERCU_3groups_Zm`, also
sold as **EGLO 99099** "3 groups remote controller").

Without this quirk the remote pairs into Home Assistant but is nearly useless:
it shows up as a plain Zigbee device with only an *Identify* button and RSSI/LQI
sensors — **no button entities and no device triggers**, so it cannot be used in
any automation. This integration adds the missing [ZHA quirk](custom_components/eglo_connect_z_remote/quirk.py):
every button press becomes a proper **device trigger** you can pick in the
automation editor.

Works fully locally — no MQTT broker, no Zigbee2MQTT, no cloud.

## Supported hardware

| Check on the device page | Supported |
| ------------------------ | --------- |
| Manufacturer **AwoX**, Model **ERCU_3groups_Zm** | ✅ yes |
| Manufacturer `_TZ3000_…`, Model **TS004F** | ❌ no (Tuya hardware — different device, different quirk) |

Settings → Devices & services → ZHA → *this remote* → the manufacturer/model
are on the device info card. The command map was validated against Zigbee2MQTT's
`eglo99099` converter and the live device signature.

## Installation (HACS)

1. **Custom repository**: HACS → ⋮ → *Custom repositories* → add
   `https://github.com/PurpleBooth/ha-eglo-connect.z-smart-home-fernbedienung-2.0`
   with category *Integration*.
2. Install **EGLO connect.z Fernbedienung 2.0**, then **restart Home
   Assistant**.
3. Settings → Devices & services → *Add integration* → **EGLO connect.z
   Fernbedienung 2.0** → Submit (just registers the quirk, nothing to fill in).
4. If the remote was already paired: restart Home Assistant once more (or run
   ZHA's *Reload quirks* action). **No re-pairing needed** — the quirk matches
   the existing device signature.
5. Open the remote's device page → ⋮ on an automation → the trigger list now
   offers every button.

## Triggers

| Button | Trigger (type / subtype) |
| ------ | ------------------------ |
| On | `remote_button_short_press` / `turn_on` |
| Off | `remote_button_short_press` / `turn_off` |
| 🔴 / 🟢 / 🔵 short | `remote_button_short_press` / `red`, `green`, `blue` |
| 🔴 / 🟢 / 🔵 long | `remote_button_long_press` / `red_long`, `green_long`, `blue_long` |
| Refresh (white) short / long | `refresh` / `refresh_long` |
| Refresh coloured short / long | `refresh_colored` / `refresh_colored_long` |
| Dim ▲ / ▼ short | `remote_button_short_press` / `dim_up`, `dim_down` |
| Dim ▲ / ▼ long | `remote_button_long_press` / `dim_up`, `dim_down` |
| Colour temp cold / warm short | `remote_button_short_press` / `color_temp_cold`, `color_temp_warm` |
| Colour temp cold / warm long | `remote_button_long_press` / `color_temp_cold`, `color_temp_warm` |
| ♥ 1 / ♥ 2 short | `remote_button_short_press` / `favorite_1`, `favorite_2` |
| ♥ 1 / ♥ 2 long | `remote_button_long_press` / `favorite_1`, `favorite_2` |

### Quirks handled for you

- **Spurious "On"** — the hardware fires an extra `on` right after the colour,
  refresh and colour-temperature buttons; the quirk suppresses it (same as
  Zigbee2MQTT).
- **Value jitter** — colour hues arrive as 254/255, 84/85, 169/170 depending on
  the press; events are normalised so one trigger per button is enough.
- The raw Zigbee parameters (levels, mireds, colour values) are still included
  in the `zha_event` payload for advanced templating.

### Persistent triggers (survive re-pairing)

Device triggers are keyed on the device id, which changes if the remote is ever
removed and re-paired. For hand-written automations you can trigger on the
`zha_event` bus with the remote's **IEEE address** instead — it survives
re-pairing (this is also the recommended ZHA pattern in Home Assistant's
[best practices](.agents/skills/home-assistant-best-practices/references/device-control.md)):

```yaml
triggers:
  - trigger: event
    event_type: zha_event
    event_data:
      device_ieee: "a4:c1:38:19:fb:cd:41:6e"  # your remote's IEEE
      command: "recall_1"
actions:
  - action: scene.turn_on
    target:
      entity_id: scene.goodnight
```

Every canonical `command` value is listed in the trigger table above
(`on`, `off`, `red`, `red_long`, … `recall_2_long`).

### Zones (group buttons 1/2/3)

The zone buttons send nothing over Zigbee — the remote instead broadcasts every
command to the active zone's Zigbee group (32778/32779/32780), and Zigbee group
ids are not part of ZHA's event payload. Triggers therefore cannot distinguish
zones. This matches Zigbee2MQTT's documented limitation; Z2M additionally
exposes `action_group` only because it reads the raw group id from MQTT.

## Blueprint

Import [`blueprints/eglo_connect_z_remote_lights.yaml`](blueprints/eglo_connect_z_remote_lights.yaml)
for a ready-made lighting automation: On/Off targets, dim stepping, Refresh =
100 % warm white, and optional actions for the two favourite buttons.

## Local development

```sh
python3 -m venv .venv
.venv/bin/pip install zigpy zha-quirks pytest
.venv/bin/pytest tests/
```

The test suite builds a device from the remote's real ZHA signature, applies
the quirk, and simulates every button press with the observed ZCL frames.

## References

- [HA community: listening for button presses on this remote](https://community.home-assistant.io/t/how-to-listen-for-button-presses-on-zigbee-remote-control/722016)
- [Zigbee2MQTT EGLO 99099](https://www.zigbee2mqtt.io/devices/99099.html)
- [Local custom ZHA quirks guide](https://community.home-assistant.io/t/zigbee-guide-how-to-add-setup-local-custom-zha-device-handlers-also-known-as-quirks-in-the-zha-integration/683473)

## License

[MIT](LICENSE)
