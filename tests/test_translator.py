"""Tests for the zha_event → action translation layer.

Payloads mirror the live captures from the real remote (AwoX ERCU_3groups_Zm
on ZHA 2026.10.4) and the Zigbee2MQTT eglo99099 converter.
"""

import pytest

from custom_components.eglo_remote.translator import (
    CLUSTER_COLOR,
    CLUSTER_LEVEL,
    CLUSTER_ON_OFF,
    CLUSTER_SCENES,
    TranslationState,
    translate_zha_event,
)


def make_state():
    return TranslationState()


def translate(cluster_id, command, args=None, params=None, group_id=None):
    data = {
        "device_ieee": "a4:c1:38:19:fb:cd:41:6e",
        "endpoint_id": 1,
        "cluster_id": cluster_id,
        "command": command,
        "args": args if args is not None else [],
        "params": params if params is not None else {},
    }
    if group_id is not None:
        data["group_id"] = group_id
    return translate_zha_event(data, make_state())


class TestOnOff:
    def test_on(self):
        assert translate(CLUSTER_ON_OFF, "on") == {"action": "on"}

    def test_off(self):
        assert translate(CLUSTER_ON_OFF, "off") == {"action": "off"}

    def test_attribute_updated_is_ignored(self):
        assert (
            translate(
                CLUSTER_ON_OFF,
                "attribute_updated",
                args=[{"attribute_id": 0, "attribute_value": 1}],
            )
            is None
        )

    def test_group_id_becomes_action_group(self):
        result = translate(CLUSTER_ON_OFF, "on", group_id=32778)
        assert result == {"action": "on", "zone": 1}

    def test_small_group_id_is_ignored(self):
        assert translate(CLUSTER_ON_OFF, "on", group_id=0) == {"action": "on"}


class TestBrightness:
    @pytest.mark.parametrize("command", ["step", "step_with_on_off"])
    def test_step_up(self, command):
        result = translate(
            CLUSTER_LEVEL,
            command,
            args=[0, 18, 2],
            params={"step_mode": 0, "step_size": 18},
        )
        assert result == {"action": "brightness_step_up"}

    @pytest.mark.parametrize("command", ["step", "step_with_on_off"])
    def test_step_down(self, command):
        result = translate(
            CLUSTER_LEVEL,
            command,
            args=[1, 18, 2],
            params={"step_mode": 1, "step_size": 18},
        )
        assert result == {"action": "brightness_step_down"}

    def test_move_to_level_up(self):
        result = translate(
            CLUSTER_LEVEL,
            "move_to_level_with_on_off",
            args=[254, 2],
            params={"level": 254, "transition_time": 2},
        )
        assert result == {"action": "brightness_move_to_level", "level": 254}

    def test_move_to_level_down(self):
        result = translate(
            CLUSTER_LEVEL,
            "move_to_level",
            args=[1, 2],
            params={"level": 1, "transition_time": 2},
        )
        assert result == {"action": "brightness_move_to_level", "level": 1}

    def test_raw_refresh_short(self):
        result = translate(CLUSTER_LEVEL, "raw_command", args=[17, 223, 16, 1, 1])
        assert result == {"action": "refresh"}

    def test_raw_refresh_short_alt_byte(self):
        result = translate(CLUSTER_LEVEL, "raw_command", args=[17, 225, 16, 0, 1])
        assert result == {"action": "refresh"}

    def test_raw_refresh_long(self):
        result = translate(CLUSTER_LEVEL, "raw_command", args=[17, 223, 16, 1, 2])
        assert result == {"action": "refresh_long"}


class TestColorTemperature:
    def test_step_mode_1_is_down(self):
        result = translate(
            CLUSTER_COLOR,
            "step_color_temp",
            args=[1, 32, 2],
            params={"step_mode": 1, "step_size": 32, "transition_time": 2},
        )
        assert result == {"action": "color_temperature_step_down"}

    def test_step_mode_3_is_up(self):
        result = translate(
            CLUSTER_COLOR,
            "step_color_temp",
            args=[3, 32, 2],
            params={"step_mode": 3, "step_size": 32, "transition_time": 2},
        )
        assert result == {"action": "color_temperature_step_up"}

    def test_move_to_color_temp_warm(self):
        result = translate(
            CLUSTER_COLOR,
            "move_to_color_temp",
            args=[454, 2],
            params={"color_temp_mireds": 454, "transition_time": 2},
        )
        assert result == {
            "action": "color_temperature_move",
            "color_temperature": 454,
        }

    def test_move_to_color_temp_cold(self):
        result = translate(
            CLUSTER_COLOR,
            "move_to_color_temp",
            args=[153, 2],
            params={"color_temp_mireds": 153, "transition_time": 2},
        )
        assert result == {
            "action": "color_temperature_move",
            "color_temperature": 153,
        }


class TestColors:
    @pytest.mark.parametrize(
        ("hue", "expected"),
        [
            (254, "red_long"),
            (255, "red_long"),
            (84, "green_long"),
            (85, "green_long"),
            (169, "blue_long"),
            (170, "blue_long"),
        ],
    )
    def test_move_to_hue_and_saturation(self, hue, expected):
        result = translate(
            CLUSTER_COLOR,
            "move_to_hue_and_saturation",
            args=[hue, 254, 2],
            params={"hue": hue, "saturation": 254, "transition_time": 2},
        )
        assert result == {"action": expected}

    @pytest.mark.parametrize(
        ("byte", "expected"),
        [
            (255, "red"),
            (254, "red"),
            (42, "yellow"),
            (41, "yellow"),
            (85, "green"),
            (84, "green"),
            (170, "blue"),
            (169, "blue"),
        ],
    )
    def test_raw_color_press(self, byte, expected):
        result = translate(
            CLUSTER_COLOR, "raw_command", args=[17, 203, 48, 0, byte, 8, 0]
        )
        assert result == {"action": expected}

    def test_raw_color_wrong_tail_is_ignored(self):
        assert (
            translate(CLUSTER_COLOR, "raw_command", args=[17, 203, 48, 0, 255, 9, 0])
            is None
        )

    def test_move_hue_rate_12_is_refresh_colored(self):
        result = translate(
            CLUSTER_COLOR,
            "move_hue",
            args=[1, 12],
            params={"move_mode": 1, "rate": 12},
        )
        assert result == {"action": "refresh_colored"}

    def test_enhanced_move_hue_short(self):
        result = translate(
            CLUSTER_COLOR,
            "enhanced_move_hue",
            args=[1, 3072],
            params={"move_mode": 1, "rate": 3072},
        )
        assert result == {"action": "refresh_colored"}

    def test_enhanced_move_hue_long(self):
        result = translate(
            CLUSTER_COLOR,
            "enhanced_move_hue",
            args=[3, 3072],
            params={"move_mode": 3, "rate": 3072},
        )
        assert result == {"action": "refresh_colored_long"}


class TestFavorites:
    @pytest.mark.parametrize(("scene", "expected"), [(1, "recall_1"), (2, "recall_2")])
    def test_recall(self, scene, expected):
        result = translate(
            CLUSTER_SCENES,
            "recall",
            args=[0, scene],
            params={"group_id": 0, "scene_id": scene, "transition_time": None},
        )
        assert result == {"action": expected}

    @pytest.mark.parametrize(
        ("scene", "expected"), [(1, "recall_1_long"), (2, "recall_2_long")]
    )
    def test_store(self, scene, expected):
        result = translate(
            CLUSTER_SCENES,
            "store",
            args=[0, scene],
            params={"group_id": 0, "scene_id": scene},
        )
        assert result == {"action": expected}

    def test_recall_other_scene_is_ignored(self):
        assert (
            translate(CLUSTER_SCENES, "recall", args=[0, 3], params={"scene_id": 3})
            is None
        )


class TestShimEvents:
    """Events emitted by the quirk shim (command `eglo_action`)."""

    def shim(self, action, **extra):
        return translate(0x0006, "eglo_action", args={"action": action, **extra})

    def test_relay_with_zone(self):
        assert self.shim("on", zone=2) == {"action": "on", "zone": 2}

    def test_relay_with_level(self):
        assert self.shim("brightness_move_to_level", level=254, zone=1) == {
            "action": "brightness_move_to_level",
            "zone": 1,
            "level": 254,
        }

    def test_relay_with_color_temperature(self):
        assert self.shim("color_temperature_move", color_temperature=454) == {
            "action": "color_temperature_move",
            "color_temperature": 454,
        }

    def test_zone_selected_action(self):
        assert self.shim("zone_selected", zone=3) == {
            "action": "zone_selected",
            "zone": 3,
        }

    def test_invalid_action_is_ignored(self):
        assert self.shim("not_a_real_action") is None

    def test_missing_action_is_ignored(self):
        assert translate(0x0006, "eglo_action", args={"zone": 2}) is None

    def test_list_args_are_ignored(self):
        assert translate(0x0006, "eglo_action", args=[1, 2]) is None


class TestSpuriousOnSuppression:
    def test_on_right_after_action_is_suppressed(self):
        state = TranslationState()
        color_event = {
            "cluster_id": CLUSTER_COLOR,
            "command": "enhanced_move_hue",
            "args": [1, 3072],
            "params": {"move_mode": 1, "rate": 3072},
        }
        assert translate_zha_event(color_event, state) == {"action": "refresh_colored"}
        on_event = {
            "cluster_id": CLUSTER_ON_OFF,
            "command": "on",
            "args": [],
            "params": {},
        }
        assert translate_zha_event(on_event, state) is None

    def test_on_after_window_is_kept(self, monkeypatch):
        state = TranslationState()
        monotonic = [0.0]
        monkeypatch.setattr(
            "custom_components.eglo_remote.translator.time.monotonic",
            lambda: monotonic[0],
        )
        color_event = {
            "cluster_id": CLUSTER_COLOR,
            "command": "step_color_temp",
            "args": [3, 32, 2],
            "params": {"step_mode": 3, "step_size": 32, "transition_time": 2},
        }
        assert translate_zha_event(color_event, state) == {
            "action": "color_temperature_step_up"
        }
        monotonic[0] += 2.0  # beyond the 0.5 s window
        on_event = {
            "cluster_id": CLUSTER_ON_OFF,
            "command": "on",
            "args": [],
            "params": {},
        }
        assert translate_zha_event(on_event, state) == {"action": "on"}

    def test_plain_on_without_prior_action_is_kept(self):
        state = TranslationState()
        on_event = {
            "cluster_id": CLUSTER_ON_OFF,
            "command": "on",
            "args": [],
            "params": {},
        }
        assert translate_zha_event(on_event, state) == {"action": "on"}

    def test_off_is_never_suppressed(self):
        state = TranslationState()
        color_event = {
            "cluster_id": CLUSTER_COLOR,
            "command": "enhanced_move_hue",
            "args": [1, 3072],
            "params": {"move_mode": 1, "rate": 3072},
        }
        translate_zha_event(color_event, state)
        off_event = {
            "cluster_id": CLUSTER_ON_OFF,
            "command": "off",
            "args": [],
            "params": {},
        }
        assert translate_zha_event(off_event, state) == {"action": "off"}


class TestIgnores:
    def test_unknown_cluster_is_ignored(self):
        assert translate(0x1234, "some_command", args=[1, 2]) is None

    def test_unknown_command_on_known_cluster_is_ignored(self):
        assert translate(CLUSTER_ON_OFF, "toggle") is None

    def test_raw_args_with_dicts_are_ignored(self):
        assert translate(CLUSTER_LEVEL, "attribute_updated", args={"a": 1}) is None

    def test_raw_args_out_of_byte_range_are_ignored(self):
        assert (
            translate(CLUSTER_LEVEL, "raw_command", args=[17, 99999, 16, 1, 1]) is None
        )
