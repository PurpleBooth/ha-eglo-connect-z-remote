"""Translate raw ZHA events from EGLO connect.z remotes into actions.

The remote transmits standard Zigbee cluster commands which ZHA forwards on
the ``zha_event`` bus event. This module maps those commands onto a stable
action vocabulary.

The mapping mirrors the Zigbee2MQTT converter for the EGLO 99099
(``ERCU_3groups_Zm``) in zigbee-herdsman-converters (``src/devices/eglo.ts``
and ``src/devices/awox.ts``), which is the best available reference for this
hardware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Final

CLUSTER_SCENES: Final = 0x0005
CLUSTER_ON_OFF: Final = 0x0006
CLUSTER_LEVEL: Final = 0x0008
CLUSTER_COLOR: Final = 0x0300  # 768, the lightingColorCtrl cluster id

# The remote emits a spurious "on" command within roughly half a second of
# most actions (color steps, scene recalls, ...). The same window is used by
# the Zigbee2MQTT converter.
SUPPRESS_ON_WINDOW: Final = 0.5

GESTURE_SHORT: Final = "short"
GESTURE_LONG: Final = "long"


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """A canonical action the integration can report."""

    name: str
    gesture: str
    subtype: str


ACTION_DEFINITIONS: Final[tuple[ActionDefinition, ...]] = (
    ActionDefinition("on", GESTURE_SHORT, "turn_on"),
    ActionDefinition("off", GESTURE_SHORT, "turn_off"),
    ActionDefinition("brightness_step_up", GESTURE_SHORT, "dim_up"),
    ActionDefinition("brightness_step_down", GESTURE_SHORT, "dim_down"),
    ActionDefinition("brightness_move_to_level", GESTURE_LONG, "brightness_move"),
    ActionDefinition(
        "color_temperature_step_up", GESTURE_SHORT, "color_temperature_up"
    ),
    ActionDefinition(
        "color_temperature_step_down", GESTURE_SHORT, "color_temperature_down"
    ),
    ActionDefinition("color_temperature_move", GESTURE_LONG, "color_temperature"),
    ActionDefinition("red", GESTURE_SHORT, "red"),
    ActionDefinition("red_long", GESTURE_LONG, "red"),
    ActionDefinition("yellow", GESTURE_SHORT, "yellow"),
    ActionDefinition("yellow_long", GESTURE_LONG, "yellow"),
    ActionDefinition("green", GESTURE_SHORT, "green"),
    ActionDefinition("green_long", GESTURE_LONG, "green"),
    ActionDefinition("blue", GESTURE_SHORT, "blue"),
    ActionDefinition("blue_long", GESTURE_LONG, "blue"),
    ActionDefinition("refresh", GESTURE_SHORT, "refresh"),
    ActionDefinition("refresh_long", GESTURE_LONG, "refresh"),
    ActionDefinition("refresh_colored", GESTURE_SHORT, "color_cycle"),
    ActionDefinition("refresh_colored_long", GESTURE_LONG, "color_cycle"),
    ActionDefinition("recall_1", GESTURE_SHORT, "group_1"),
    ActionDefinition("recall_1_long", GESTURE_LONG, "group_1"),
    ActionDefinition("recall_2", GESTURE_SHORT, "group_2"),
    ActionDefinition("recall_2_long", GESTURE_LONG, "group_2"),
)

ACTION_NAMES: Final[frozenset[str]] = frozenset(
    definition.name for definition in ACTION_DEFINITIONS
)


class TranslationState:
    """Per-device state used to suppress the remote's spurious 'on' events."""

    __slots__ = ("_last_non_on",)

    def __init__(self) -> None:
        """Initialize state with suppression disabled."""
        self._last_non_on = float("-inf")

    def mark_non_on(self) -> None:
        """Record that a non-'on' action was just seen."""
        self._last_non_on = time.monotonic()

    def suppress_on(self) -> bool:
        """Return True while a spurious 'on' is expected."""
        return (time.monotonic() - self._last_non_on) < SUPPRESS_ON_WINDOW


def _arg(args: Any, index: int) -> Any:
    """Return a positional argument, or None when missing."""
    if isinstance(args, (list, tuple)) and len(args) > index:
        return args[index]
    return None


def _as_buffer(args: Any) -> tuple[int, ...] | None:
    """Interpret event args as a Zigbee raw payload buffer when possible."""
    if isinstance(args, bytes):
        return tuple(args)
    if isinstance(args, (list, tuple)) and all(
        isinstance(item, int) and 0 <= item <= 0xFF for item in args
    ):
        return tuple(args)
    return None


def _translate_raw_refresh(raw: tuple[int, ...]) -> str | None:
    """Map the raw genLevelCtrl payload of the refresh button."""
    if len(raw) < 5 or raw[0] != 17 or raw[2] != 16:
        return None
    if raw[3] in (0, 1) and raw[4] == 1:
        return "refresh"
    if raw[3] == 1 and raw[4] == 2:
        return "refresh_long"
    return None


def _translate_raw_color(raw: tuple[int, ...]) -> str | None:
    """Map the raw lightingColorCtrl payload of the direct color buttons."""
    if len(raw) < 7 or raw[0] != 17 or raw[2] != 48 or raw[3] != 0:
        return None
    if raw[5] != 8 or raw[6] != 0:
        return None
    if raw[4] in (254, 255):
        return "red"
    if raw[4] in (41, 42):
        return "yellow"
    if raw[4] in (84, 85):
        return "green"
    if raw[4] in (169, 170):
        return "blue"
    return None


def _translate_color_hue(hue: Any) -> str | None:
    """Map the hue of a long-press color command (MoveToHueAndSaturation)."""
    if hue in (254, 255):
        return "red_long"
    if hue in (41, 42):
        return "yellow_long"
    if hue in (84, 85):
        return "green_long"
    if hue in (169, 170):
        return "blue_long"
    return None


def translate_zha_event(
    data: dict[str, Any], state: TranslationState
) -> dict[str, Any] | None:
    """Map one ``zha_event`` payload to an action payload.

    Returns None when the event is not a user-facing button action, for
    example attribute updates or the spurious 'on' the remote emits after
    many commands.
    """
    cluster_id = data.get("cluster_id")
    command = data.get("command") or ""
    params: dict[str, Any] = data.get("params") or {}
    args: Any = data.get("args") or []

    action: str | None = None
    extra: dict[str, Any] = {}

    if cluster_id == CLUSTER_ON_OFF:
        if command == "on":
            if state.suppress_on():
                return None
            action = "on"
        elif command == "off":
            action = "off"

    elif cluster_id == CLUSTER_LEVEL:
        if command in ("step", "step_with_on_off"):
            # ZCL step mode: 0 = up, 1 = down.
            step_mode = params.get("step_mode", _arg(args, 0))
            action = "brightness_step_up" if step_mode == 0 else "brightness_step_down"
        elif command in ("move_to_level", "move_to_level_with_on_off"):
            action = "brightness_move_to_level"
            level = params.get("level", _arg(args, 0))
            if level is not None:
                extra["level"] = level
        else:
            raw = _as_buffer(args)
            if raw is not None:
                action = _translate_raw_refresh(raw)
                if action is not None:
                    state.mark_non_on()

    elif cluster_id == CLUSTER_COLOR:
        if command == "step_color_temp":
            # This remote reports step mode 1 for one direction and 3 for the
            # other, inverted versus the ZCL direction assignment. The
            # Zigbee2MQTT converter observed 1 = down, 3 = up.
            step_mode = params.get("step_mode", _arg(args, 0))
            action = (
                "color_temperature_step_up"
                if step_mode == 3
                else "color_temperature_step_down"
            )
            state.mark_non_on()
        elif command == "move_to_color_temp":
            action = "color_temperature_move"
            color_temperature = params.get("color_temp_mireds", _arg(args, 0))
            if color_temperature is not None:
                extra["color_temperature"] = color_temperature
            state.mark_non_on()
        elif command == "move_to_hue_and_saturation":
            action = _translate_color_hue(params.get("hue", _arg(args, 0)))
            if action is not None:
                state.mark_non_on()
        elif command == "move_hue":
            if (
                params.get("move_mode", _arg(args, 0)) == 1
                and params.get("rate", _arg(args, 1)) == 12
            ):
                action = "refresh_colored"
                state.mark_non_on()
        elif command == "enhanced_move_hue":
            move_mode = params.get("move_mode", _arg(args, 0))
            if move_mode == 1:
                action = "refresh_colored"
                state.mark_non_on()
            elif move_mode == 3:
                action = "refresh_colored_long"
                state.mark_non_on()
        else:
            raw = _as_buffer(args)
            if raw is not None:
                action = _translate_raw_color(raw)
                if action is not None:
                    state.mark_non_on()

    elif cluster_id == CLUSTER_SCENES:
        if command == "recall":
            scene_id = params.get("scene_id", _arg(args, 1))
            if scene_id in (1, 2):
                action = f"recall_{scene_id}"
        elif command == "store":
            scene_id = params.get("scene_id", _arg(args, 1))
            if scene_id in (1, 2):
                action = f"recall_{scene_id}_long"

    if action is None:
        return None

    payload: dict[str, Any] = {"action": action}
    group_id = data.get("group_id")
    if isinstance(group_id, int) and group_id >= 32778:
        payload["action_group"] = group_id - 32777
    payload.update(extra)
    return payload
