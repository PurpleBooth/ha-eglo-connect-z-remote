"""ZHA quirk shim for the EGLO connect.z remotes (AwoX ERCU_*).

zigpy silently drops the remote's vendor-specific raw commands (0x30 on the
Color cluster for the direct colour buttons, 0x10 on LevelControl for the
refresh button), and zha_event payloads carry no Zigbee group id, so the
remote's active zone is invisible. This shim fixes both:

* It defines the two vendor commands so zigpy can parse them.
* Its clusters take over decoding of the remote's output-cluster commands and
  emit a single canonical ``eglo_action`` zha_event per press, carrying the
  action name, the zone the press targeted (group 32778..32780 -> 1..3) and
  any raw values (level, colour temperature). The base ``handle_message``
  path is bypassed for decoded commands, so no duplicate standard events are
  emitted; anything the shim cannot decode falls through to normal zigpy
  handling.
* It suppresses the hardware's spurious ``on`` within 500 ms of action
  buttons (colour, refresh, colour temperature, scenes), matching the
  Zigbee2MQTT converter.

Command map mirrors the Zigbee2MQTT ``eglo99099`` converter
(zigbee-herdsman-converters ``src/devices/eglo.ts`` + ``src/devices/awox.ts``).
When the shim is not applied, the integration still works from the standard
zha_events, minus the colour and refresh buttons and the zone information.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import zigpy.types as t
from zhaquirks import EventableCluster
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
    ZHA_SEND_EVENT,
)
from zhaquirks.legacy import CustomDevice
from zigpy.profiles import zha
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    LevelControl,
    OnOff,
    Scenes,
)
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.clusters.lightlink import LightLink

MANUFACTURER = "AwoX"
MODELS = ("ERCU_3groups_Zm", "ERCU_Zm")

COMMAND_ID_AWOX_COLOR = 0x30  # vendor raw command on the Color cluster
COMMAND_ID_AWOX_REFRESH = 0x10  # vendor raw command on the LevelControl cluster

# Group ids the remote broadcasts to for its three zones; the zone number is
# the group id minus 32777.
ZONE_GROUP_FIRST = 32778
ZONE_GROUP_LAST = 32780

# The remote emits a spurious "on" within roughly half a second of colour,
# refresh, colour-temperature and scene presses (Z2M uses the same window).
SPURIOUS_ON_WINDOW = 0.5

# Direct colour buttons send the colour byte with ±1 jitter.
COLOR_BY_BYTE = {
    255: "red",
    254: "red",
    42: "yellow",
    41: "yellow",
    85: "green",
    84: "green",
    170: "blue",
    169: "blue",
}

# Long presses move to hue/saturation instead of the raw vendor command.

# step_color_temp step modes are vendor-specific: 1 = warmer, 3 = colder.
TEMP_STEP_WARM = 1
TEMP_STEP_COLD = 3

# enhanced_move_hue move modes: 1 = short press, 3 = long press of the
# colour-cycle button; the older move_hue reports mode 1 with rate 12.
MOVE_MODE_SHORT = 1
MOVE_MODE_LONG = 3
COLOR_CYCLE_MOVE_HUE_RATE = 12

# Refresh button raw payload: press byte 1 = short, 2 = long.
REFRESH_PRESS_SHORT = 1
REFRESH_PRESS_LONG = 2


class EgloShimMixin:
    """Shared state and event emission for the shim clusters.

    All state lives on the device so it is shared between the four clusters.
    """

    HANDLED_COMMANDS: ClassVar[frozenset[str]] = frozenset()

    @property
    def _eglo_device(self) -> Any:
        """Return the zigpy device owning this cluster."""
        return self.endpoint.device

    def _eglo_zone(self) -> int | None:
        """Return the zone the most recent frame was broadcast to."""
        zone = getattr(self._eglo_device, "_eglo_current_zone", None)
        return zone if zone in (1, 2, 3) else None

    def _eglo_mark_action(self) -> None:
        """Record that a spurious-'on'-triggering button was pressed."""
        self._eglo_device._eglo_last_action_at = time.monotonic()

    def _eglo_is_spurious_on(self) -> bool:
        """Return True while the spurious 'on' after an action is expected."""
        last = getattr(self._eglo_device, "_eglo_last_action_at", None)
        return last is not None and (time.monotonic() - last) < SPURIOUS_ON_WINDOW

    def _eglo_emit(self, action: str, **extra: Any) -> None:
        """Emit one canonical eglo_action event.

        When the broadcast zone differs from the last one seen, an extra
        ``zone_selected`` action is emitted first: the zone buttons themselves
        transmit nothing over Zigbee, so a zone switch only becomes visible on
        the next press.
        """
        device = self._eglo_device
        zone = self._eglo_zone()
        if zone is not None and zone != getattr(device, "_eglo_last_zone", None):
            device._eglo_last_zone = zone
            self.listener_event(
                ZHA_SEND_EVENT,
                "eglo_action",
                {"action": "zone_selected", "zone": zone},
            )
        payload: dict[str, Any] = {"action": action}
        if zone is not None:
            payload["zone"] = zone
        payload.update(
            {key: value for key, value in extra.items() if value is not None}
        )
        self.listener_event(ZHA_SEND_EVENT, "eglo_action", payload)

    def _eglo_command_name(self, hdr: foundation.ZCLHeader) -> str | None:
        """Return the name of the received server command, if known."""
        command = self.server_commands.get(hdr.command_id)
        return command.name if command is not None else None

    def try_handle(self, hdr: foundation.ZCLHeader, args: Any) -> bool:
        """Decode a command into an eglo_action event.

        Returns False when this command is not one the shim decodes; the
        caller then falls through to the normal zigpy handling.
        """
        raise NotImplementedError

    def handle_message(self, hdr: foundation.ZCLHeader, args: Any) -> None:
        """Take over decoded commands so no duplicate standard event fires."""
        if (
            hdr.frame_control.is_cluster
            and self._eglo_command_name(hdr) in self.HANDLED_COMMANDS
            and self.try_handle(hdr, args)
        ):
            return
        super().handle_message(hdr, args)


class EgloColorCluster(EgloShimMixin, EventableCluster, Color):
    """Color cluster decoding colour buttons and colour-cycle presses."""

    server_commands = Color.server_commands.copy()
    server_commands[COMMAND_ID_AWOX_COLOR] = foundation.ZCLCommandDef(
        "awox_color_press",
        {
            "param1": t.uint8_t,
            "color": t.uint8_t,
            "tail1": t.uint8_t,
            "tail2": t.uint8_t,
        },
        is_manufacturer_specific=True,
    )

    HANDLED_COMMANDS: ClassVar[frozenset[str]] = frozenset(
        {
            "awox_color_press",
            "move_to_hue_and_saturation",
            "enhanced_move_hue",
            "move_hue",
            "step_color_temp",
            "move_to_color_temp",
        }
    )

    def try_handle(self, hdr: foundation.ZCLHeader, args: Any) -> bool:
        """Decode colour, colour-cycle and colour-temperature presses."""
        name = self._eglo_command_name(hdr)

        if name == "awox_color_press":
            color = COLOR_BY_BYTE.get(args.color)
            if color is None:
                return False
            self._eglo_mark_action()
            self._eglo_emit(color)
            return True

        if name == "move_to_hue_and_saturation":
            color = COLOR_BY_BYTE.get(args.hue)
            if color is None:
                return False
            self._eglo_mark_action()
            self._eglo_emit(f"{color}_long")
            return True

        if name == "enhanced_move_hue":
            if args.move_mode not in (MOVE_MODE_SHORT, MOVE_MODE_LONG):
                return False
            self._eglo_mark_action()
            self._eglo_emit(
                "refresh_colored_long"
                if args.move_mode == MOVE_MODE_LONG
                else "refresh_colored"
            )
            return True

        if name == "move_hue":
            if (
                args.move_mode != MOVE_MODE_SHORT
                or args.rate != COLOR_CYCLE_MOVE_HUE_RATE
            ):
                return False
            self._eglo_mark_action()
            self._eglo_emit("refresh_colored")
            return True

        if name == "step_color_temp":
            if args.step_mode not in (TEMP_STEP_WARM, TEMP_STEP_COLD):
                return False
            self._eglo_mark_action()
            self._eglo_emit(
                "color_temperature_step_up"
                if args.step_mode == TEMP_STEP_COLD
                else "color_temperature_step_down"
            )
            return True

        if name == "move_to_color_temp":
            self._eglo_mark_action()
            self._eglo_emit(
                "color_temperature_move", color_temperature=args.color_temp_mireds
            )
            return True

        return False


class EgloLevelControlCluster(EgloShimMixin, EventableCluster, LevelControl):
    """LevelControl cluster decoding the refresh button and dim presses."""

    server_commands = LevelControl.server_commands.copy()
    server_commands[COMMAND_ID_AWOX_REFRESH] = foundation.ZCLCommandDef(
        "awox_refresh_press",
        {"param1": t.uint8_t, "press": t.uint8_t},
        is_manufacturer_specific=True,
    )

    HANDLED_COMMANDS: ClassVar[frozenset[str]] = frozenset(
        {
            "awox_refresh_press",
            "step",
            "step_with_on_off",
            "move_to_level",
            "move_to_level_with_on_off",
        }
    )

    def try_handle(self, hdr: foundation.ZCLHeader, args: Any) -> bool:
        """Decode refresh and dim presses."""
        name = self._eglo_command_name(hdr)

        if name == "awox_refresh_press":
            self._eglo_mark_action()
            if args.press == REFRESH_PRESS_LONG:
                self._eglo_emit("refresh_long")
            elif args.press == REFRESH_PRESS_SHORT:
                self._eglo_emit("refresh")
            else:
                return False
            return True

        if name in ("step", "step_with_on_off"):
            if args.step_mode == 0:  # ZCL StepMode.Up
                self._eglo_emit("brightness_step_up")
            elif args.step_mode == 1:  # ZCL StepMode.Down
                self._eglo_emit("brightness_step_down")
            else:
                return False
            return True

        if name in ("move_to_level", "move_to_level_with_on_off"):
            self._eglo_emit("brightness_move_to_level", level=args.level)
            return True

        return False


class EgloOnOffCluster(EgloShimMixin, EventableCluster, OnOff):
    """OnOff cluster that suppresses the remote's spurious `on` presses."""

    HANDLED_COMMANDS: ClassVar[frozenset[str]] = frozenset({"on", "off"})

    def try_handle(self, hdr: foundation.ZCLHeader, args: Any) -> bool:
        """Emit on/off, swallowing spurious 'on' presses."""
        name = self._eglo_command_name(hdr)

        if name == "on":
            if self._eglo_is_spurious_on():
                self.debug("Suppressing spurious 'on' after action button press")
                return True
            self._eglo_emit("on")
            return True

        if name == "off":
            self._eglo_emit("off")
            return True

        return False


class EgloScenesCluster(EgloShimMixin, EventableCluster, Scenes):
    """Scenes cluster naming the two favourite buttons by scene id."""

    HANDLED_COMMANDS: ClassVar[frozenset[str]] = frozenset({"recall", "store"})

    def try_handle(self, hdr: foundation.ZCLHeader, args: Any) -> bool:
        """Emit recall_N / recall_N_long for favourite presses."""
        name = self._eglo_command_name(hdr)
        scene_id = getattr(args, "scene_id", None)

        if name == "recall" and scene_id in (1, 2):
            self._eglo_mark_action()
            self._eglo_emit(f"recall_{scene_id}")
            return True

        if name == "store" and scene_id in (1, 2):
            self._eglo_mark_action()
            self._eglo_emit(f"recall_{scene_id}_long")
            return True

        return False


class EgloRemoteShim(CustomDevice):
    """Shim device for the AwoX-built EGLO connect.z remotes.

    Besides the cluster replacements, this captures the Zigbee group of every
    received frame (the remote broadcasts to the active zone's group) so the
    clusters can attach the zone number to each action.
    """

    signature: ClassVar[dict] = {
        MODELS_INFO: [(MANUFACTURER, model) for model in MODELS],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COLOR_CONTROLLER,  # 0x0800
                INPUT_CLUSTERS: [
                    0x0000,  # Basic
                    0x0003,  # Identify
                    0x0004,  # Groups
                    LightLink.cluster_id,  # 0x1000
                ],
                OUTPUT_CLUSTERS: [
                    0x0000,  # Basic
                    0x0003,  # Identify
                    0x0004,  # Groups
                    0x0005,  # Scenes
                    0x0006,  # OnOff
                    0x0008,  # LevelControl
                    0x0300,  # Color
                    LightLink.cluster_id,  # 0x1000
                ],
            },
            3: {
                PROFILE_ID: 0x128F,
                DEVICE_TYPE: zha.DeviceType.COLOR_CONTROLLER,
                INPUT_CLUSTERS: [0xFF50, 0xFF51],
                OUTPUT_CLUSTERS: [0xFF50, 0xFF51],
            },
        },
    }

    replacement: ClassVar[dict] = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COLOR_CONTROLLER,
                INPUT_CLUSTERS: [
                    0x0000,
                    0x0003,
                    0x0004,
                    LightLink.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    0x0000,
                    0x0003,
                    0x0004,
                    EgloScenesCluster,
                    EgloOnOffCluster,
                    EgloLevelControlCluster,
                    EgloColorCluster,
                    LightLink.cluster_id,
                ],
            },
            3: {
                PROFILE_ID: 0x128F,
                DEVICE_TYPE: zha.DeviceType.COLOR_CONTROLLER,
                INPUT_CLUSTERS: [0xFF50, 0xFF51],
                OUTPUT_CLUSTERS: [0xFF50, 0xFF51],
            },
        }
    }

    def packet_received(self, packet: t.ZigbeePacket) -> None:
        """Capture the broadcast zone before dispatching the frame."""
        dst = getattr(packet, "dst", None)
        addr = getattr(dst, "address", None)
        if getattr(dst, "addr_mode", None) == t.AddrMode.Group and isinstance(
            addr, int
        ):
            if ZONE_GROUP_FIRST <= addr <= ZONE_GROUP_LAST:
                self._eglo_current_zone = addr - 32777
            else:
                self._eglo_current_zone = None
        super().packet_received(packet)
