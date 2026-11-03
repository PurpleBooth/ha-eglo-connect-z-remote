"""ZHA quirk for the EGLO connect.z Fernbedienung 2.0 (AwoX ERCU_3groups_Zm).

Also sold as EGLO 99099 "3 groups remote controller" (AwoX TLSR82xx hardware).

Without this quirk the remote pairs into ZHA but produces no entities and no
device triggers: button presses arrive as vendor-raw ZCL commands that modern
ZHA only turns into ``zha_event``/device triggers when a quirk emits them via
``zha_send_event``.

The command map below mirrors Zigbee2MQTT's ``eglo99099`` converter
(``zigbee-herdsman-converters/src/devices/eglo.ts``), which was derived from
the same hardware:

=====================  ===========================  ====================================
Button                 Short press                  Long press
=====================  ===========================  ====================================
On                     OnOff ``on`` (0x00)          —
Off                    OnOff ``off`` (0x00)         —
Red / Green / Blue     Color raw 0x30               Color ``move_to_hue_and_saturation``
Refresh (white)        LevelControl raw 0x10        LevelControl raw 0x10 (press=2)
Refresh colored        Color ``enhanced_move_hue``  Color ``enhanced_move_hue`` (mode 3)
                       or ``move_hue`` (mode 1)
Dim up / down          LevelControl ``step*``       LevelControl ``move_to_level*``
Warm / Cold            Color ``step_color_temp``    Color ``move_to_color_temp``
Favourite 1 / 2        Scenes ``recall`` 1/2        Scenes ``store`` 1/2
=====================  ===========================  ====================================

Zones (the 1/2/3 group buttons) are *not* addressable over Zigbee: the remote
broadcasts every command to the active zone's Zigbee group (32778/32779/32780)
and those group ids do not reach the ``zha_event`` payload.

Two quirks of the hardware are normalised away, matching Z2M behaviour:

* The remote emits a spurious ``on`` ~within 500 ms after colour, refresh and
  colour-temperature presses; the quirk suppresses it.
* The remote sends colour values with ±1 jitter (hue 254/255 etc.) and uses
  out-of-spec move/step mode 3; the quirk normalises them into one canonical
  ``zha_event`` command name per physical button action.
"""

from __future__ import annotations

import time
from typing import Any

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    Basic,
    Groups,
    Identify,
    LevelControl,
    OnOff,
    Scenes,
)
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.clusters.lightlink import LightLink

from zhaquirks import EventableCluster
from zhaquirks.const import (
    CLUSTER_ID,
    COMMAND,
    DEVICE_TYPE,
    DIM_DOWN,
    DIM_UP,
    ENDPOINT_ID,
    ENDPOINTS,
    INPUT_CLUSTERS,
    LONG_PRESS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
    SHORT_PRESS,
    TURN_OFF,
    TURN_ON,
)
from zhaquirks.legacy import CustomDevice
from zhaquirks.const import ZHA_SEND_EVENT

MANUFACTURER = "AwoX"
MODEL = "ERCU_3groups_Zm"

# Vendor-raw ZCL command ids used by the remote.
COMMAND_ID_AWOX_COLOR = 0x30  # on the Color cluster (cluster 0x0300)
COMMAND_ID_AWOX_REFRESH = 0x10  # on the LevelControl cluster (cluster 0x0008)

# Colour byte -> canonical colour name. The remote sends the value with ±1
# jitter, hence the two entries per colour.
COLOR_BY_BYTE = {
    255: "red",
    254: "red",
    85: "green",
    84: "green",
    170: "blue",
    169: "blue",
}

# Hue used by long presses, normalised like the short-press bytes.
HUE_BY_COLOR = {"red": 255, "green": 85, "blue": 170}

# A step_color_temp step_mode of 1 (ZCL "down" = warmer) and 3 (vendor value,
# colder) distinguish the two colour-temperature buttons.
STEP_MODE_WARM = 1
STEP_MODE_COLD = 3

# enhanced_move_hue move_mode 1 = short press of the refresh-coloured button,
# 3 = long press (again a vendor value outside the ZCL MoveMode enum).
MOVE_MODE_SHORT = 1
MOVE_MODE_LONG = 3

# move_to_color_temp target mireds: cold ≈ 153, warm ≈ 454. Anything above this
# threshold is treated as a warm press.
MIREDS_WARM_THRESHOLD = 300

# Levels carried by move_to_level long presses: 254 = dim up, 1 = dim down.
LEVEL_MAX = 254
LEVEL_MIN = 1

# The remote fires a spurious `on` right after colour/refresh/temp buttons.
SPURIOUS_ON_WINDOW_S = 0.5

COLOR_CL = 0x0300
LEVEL_CL = 0x0008
ONOFF_CL = 0x0006
SCENES_CL = 0x0005

EP_1 = 1


def _mark_action(cluster: Any) -> None:
    """Record that a spurious-`on`-triggering button was pressed."""
    cluster.endpoint.device._eglo_last_action_at = time.monotonic()  # noqa: SLF001


def _is_spurious_on(cluster: Any) -> bool:
    """Return True if an `on` arrives right after an action button."""
    last = getattr(cluster.endpoint.device, "_eglo_last_action_at", None)
    return last is not None and (time.monotonic() - last) < SPURIOUS_ON_WINDOW_S


class _ColorPress(foundation.CommandSchema):
    """Normalised payload for colour button events."""

    color: t.uint8_t


class _LevelPress(foundation.CommandSchema):
    """Normalised payload for dim long-press events."""

    level: t.uint8_t


class _TempPress(foundation.CommandSchema):
    """Normalised payload for colour-temperature move events."""

    color_temp_mireds: t.uint16_t


class _RefreshPress(foundation.CommandSchema):
    """Normalised payload for refresh button events."""

    press: t.uint8_t


class EgloOnOffCluster(EventableCluster, OnOff):
    """OnOff cluster that suppresses the remote's spurious `on` presses."""

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: Any,
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Swallow `on` presses that follow colour/refresh/temp actions."""
        command = self.server_commands.get(hdr.command_id)
        if command is not None and command.name == "on":
            if _is_spurious_on(self):
                self.debug("Suppressing spurious 'on' after action button press")
                return
        super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)


class EgloLevelControlCluster(EventableCluster, LevelControl):
    """LevelControl cluster decoding the raw refresh button and dim presses."""

    server_commands = LevelControl.server_commands.copy()
    server_commands[COMMAND_ID_AWOX_REFRESH] = foundation.ZCLCommandDef(
        "awox_refresh_press",
        {"param1": t.uint8_t, "press": t.uint8_t},
        is_manufacturer_specific=True,
    )

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: Any,
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Normalise refresh and dim presses into canonical event names."""
        command = self.server_commands.get(hdr.command_id)
        name = command.name if command is not None else None

        if name == "awox_refresh_press":
            _mark_action(self)
            if args.press == 2:
                self.listener_event(
                    ZHA_SEND_EVENT, "refresh_long", _RefreshPress(press=2)
                )
            else:
                self.listener_event(
                    ZHA_SEND_EVENT, "refresh", _RefreshPress(press=1)
                )
            return

        if name in ("step", "step_with_on_off"):
            if args.step_mode == 0:  # ZCL StepMode.Up
                self.listener_event(ZHA_SEND_EVENT, "brightness_step_up", args)
            elif args.step_mode == 1:  # ZCL StepMode.Down
                self.listener_event(ZHA_SEND_EVENT, "brightness_step_down", args)
            else:
                super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)
            return

        if name in ("move_to_level", "move_to_level_with_on_off"):
            event = (
                "brightness_move_up" if args.level >= 0x80 else "brightness_move_down"
            )
            self.listener_event(ZHA_SEND_EVENT, event, _LevelPress(level=args.level))
            return

        super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)


class EgloColorCluster(EventableCluster, Color):
    """Color cluster decoding the vendor colour buttons and temp presses."""

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

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: Any,
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Normalise colour, refresh-coloured and temperature presses."""
        command = self.server_commands.get(hdr.command_id)
        name = command.name if command is not None else None

        if name == "awox_color_press":
            _mark_action(self)
            color = COLOR_BY_BYTE.get(args.color)
            if color is not None:
                self.listener_event(
                    ZHA_SEND_EVENT, color, _ColorPress(color=HUE_BY_COLOR[color])
                )
            else:
                super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)
            return

        if name == "move_to_hue_and_saturation":
            color = COLOR_BY_BYTE.get(args.hue)
            if color is not None:
                _mark_action(self)
                self.listener_event(
                    ZHA_SEND_EVENT,
                    f"{color}_long",
                    _ColorPress(color=HUE_BY_COLOR[color]),
                )
            else:
                super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)
            return

        if name in ("enhanced_move_hue", "move_hue"):
            if args.move_mode == MOVE_MODE_SHORT:
                _mark_action(self)
                self.listener_event(
                    ZHA_SEND_EVENT, "refresh_colored", _RefreshPress(press=1)
                )
            elif name == "enhanced_move_hue" and args.move_mode == MOVE_MODE_LONG:
                _mark_action(self)
                self.listener_event(
                    ZHA_SEND_EVENT, "refresh_colored_long", _RefreshPress(press=2)
                )
            else:
                super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)
            return

        if name == "step_color_temp":
            if args.step_mode == STEP_MODE_WARM:
                _mark_action(self)
                self.listener_event(
                    ZHA_SEND_EVENT, "color_temperature_step_down", args
                )
            elif args.step_mode == STEP_MODE_COLD:
                _mark_action(self)
                self.listener_event(ZHA_SEND_EVENT, "color_temperature_step_up", args)
            else:
                super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)
            return

        if name == "move_to_color_temp":
            _mark_action(self)
            if args.color_temp_mireds < MIREDS_WARM_THRESHOLD:
                self.listener_event(
                    ZHA_SEND_EVENT,
                    "color_temperature_move_up",
                    _TempPress(color_temp_mireds=args.color_temp_mireds),
                )
            else:
                self.listener_event(
                    ZHA_SEND_EVENT,
                    "color_temperature_move_down",
                    _TempPress(color_temp_mireds=args.color_temp_mireds),
                )
            return

        super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)


class EgloScenesCluster(EventableCluster, Scenes):
    """Scenes cluster naming the two favourite buttons by scene id."""

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: Any,
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Emit `recall_N` / `recall_N_long` for favourite presses."""
        command = self.server_commands.get(hdr.command_id)
        name = command.name if command is not None else None

        if name == "recall" and args.scene_id in (1, 2):
            self.listener_event(ZHA_SEND_EVENT, f"recall_{args.scene_id}", args)
            return

        if name == "store" and args.scene_id in (1, 2):
            self.listener_event(
                ZHA_SEND_EVENT, f"recall_{args.scene_id}_long", args
            )
            return

        super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)


class EgloConnectZRemote(CustomDevice):
    """EGLO connect.z Fernbedienung 2.0 (AwoX ERCU_3groups_Zm / EGLO 99099)."""

    signature = {
        MODELS_INFO: [(MANUFACTURER, MODEL)],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COLOR_CONTROLLER,  # 0x0800
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    LightLink.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    OnOff.cluster_id,
                    LevelControl.cluster_id,
                    Color.cluster_id,
                    LightLink.cluster_id,
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

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COLOR_CONTROLLER,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    LightLink.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
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

    device_automation_triggers = {
        # Power
        (SHORT_PRESS, TURN_ON): {
            COMMAND: "on",
            CLUSTER_ID: ONOFF_CL,
            ENDPOINT_ID: EP_1,
        },
        (SHORT_PRESS, TURN_OFF): {
            COMMAND: "off",
            CLUSTER_ID: ONOFF_CL,
            ENDPOINT_ID: EP_1,
        },
        # Colour buttons
        (SHORT_PRESS, "red"): {
            COMMAND: "red",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "red"): {
            COMMAND: "red_long",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (SHORT_PRESS, "green"): {
            COMMAND: "green",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "green"): {
            COMMAND: "green_long",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (SHORT_PRESS, "blue"): {
            COMMAND: "blue",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "blue"): {
            COMMAND: "blue_long",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        # Refresh (white) button
        (SHORT_PRESS, "refresh"): {
            COMMAND: "refresh",
            CLUSTER_ID: LEVEL_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "refresh"): {
            COMMAND: "refresh_long",
            CLUSTER_ID: LEVEL_CL,
            ENDPOINT_ID: EP_1,
        },
        # Refresh coloured button
        (SHORT_PRESS, "refresh_colored"): {
            COMMAND: "refresh_colored",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "refresh_colored"): {
            COMMAND: "refresh_colored_long",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        # Dimming
        (SHORT_PRESS, DIM_UP): {
            COMMAND: "brightness_step_up",
            CLUSTER_ID: LEVEL_CL,
            ENDPOINT_ID: EP_1,
        },
        (SHORT_PRESS, DIM_DOWN): {
            COMMAND: "brightness_step_down",
            CLUSTER_ID: LEVEL_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, DIM_UP): {
            COMMAND: "brightness_move_up",
            CLUSTER_ID: LEVEL_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, DIM_DOWN): {
            COMMAND: "brightness_move_down",
            CLUSTER_ID: LEVEL_CL,
            ENDPOINT_ID: EP_1,
        },
        # Colour temperature
        (SHORT_PRESS, "color_temp_cold"): {
            COMMAND: "color_temperature_step_up",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (SHORT_PRESS, "color_temp_warm"): {
            COMMAND: "color_temperature_step_down",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "color_temp_cold"): {
            COMMAND: "color_temperature_move_up",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "color_temp_warm"): {
            COMMAND: "color_temperature_move_down",
            CLUSTER_ID: COLOR_CL,
            ENDPOINT_ID: EP_1,
        },
        # Favourites
        (SHORT_PRESS, "favorite_1"): {
            COMMAND: "recall_1",
            CLUSTER_ID: SCENES_CL,
            ENDPOINT_ID: EP_1,
        },
        (SHORT_PRESS, "favorite_2"): {
            COMMAND: "recall_2",
            CLUSTER_ID: SCENES_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "favorite_1"): {
            COMMAND: "recall_1_long",
            CLUSTER_ID: SCENES_CL,
            ENDPOINT_ID: EP_1,
        },
        (LONG_PRESS, "favorite_2"): {
            COMMAND: "recall_2_long",
            CLUSTER_ID: SCENES_CL,
            ENDPOINT_ID: EP_1,
        },
    }
