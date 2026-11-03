"""Simulate every button press of the EGLO Fernbedienung 2.0 against the quirk.

Frame payloads mirror the observed wire format documented in Zigbee2MQTT's
``eglo99099`` converter (zigbee-herdsman-converters/src/devices/eglo.ts).
"""

import time

import pytest

from conftest import build_device_from_live_signature, press


def u16(value: int) -> bytes:
    return value.to_bytes(2, "little")


class TestQuirkResolution:
    def test_quirk_matches_live_signature(self, quirk_module):
        from zhaquirks.legacy import get_device

        quirked = get_device(build_device_from_live_signature())
        assert isinstance(quirked, quirk_module.EgloConnectZRemote)

    def test_other_model_does_not_match(self, quirk_module):
        from zhaquirks.legacy import get_device

        device = build_device_from_live_signature()
        device.model = "SomeOtherRemote"
        quirked = get_device(device)
        assert not isinstance(quirked, quirk_module.EgloConnectZRemote)


class TestPowerButtons:
    def test_on(self, remote, capture):
        press(remote, 6, bytes([0x01]))
        assert capture.names == ["on"]

    def test_off(self, remote, capture):
        press(remote, 6, bytes([0x00]))
        assert capture.names == ["off"]

    def test_spurious_on_after_colour_press_is_suppressed(self, remote, capture):
        press(remote, 0x300, bytes([0x30, 0x00, 0xFF, 0x08, 0x00]))
        press(remote, 6, bytes([0x01]))  # spurious on, <500ms later
        assert capture.names == ["red"]

    def test_on_after_window_is_kept(self, remote, capture):
        press(remote, 0x300, bytes([0x30, 0x00, 0xFF, 0x08, 0x00]))
        remote._eglo_last_action_at = time.monotonic() - 1
        press(remote, 6, bytes([0x01]))
        assert capture.names == ["red", "on"]

    def test_plain_on_without_prior_action(self, remote, capture):
        press(remote, 6, bytes([0x01]))
        assert capture.names == ["on"]


class TestColourButtons:
    @pytest.mark.parametrize(
        ("byte", "expected"),
        [(0xFF, "red"), (0xFE, "red"), (0x55, "green"), (0x54, "green"),
         (0xAA, "blue"), (0xA9, "blue")],
    )
    def test_short_press_normalises_jitter(self, remote, capture, byte, expected):
        press(remote, 0x300, bytes([0x30, 0x00, byte, 0x08, 0x00]))
        assert capture.names == [expected]
        assert capture.params(expected)["color"] == {"red": 255, "green": 85,
                                                     "blue": 170}[expected]

    @pytest.mark.parametrize(
        ("hue", "expected"),
        [(0xFF, "red_long"), (0xFE, "red_long"), (0x55, "green_long"),
         (0x54, "green_long"), (0xAA, "blue_long"), (0xA9, "blue_long")],
    )
    def test_long_press_via_move_to_hue_and_saturation(
        self, remote, capture, hue, expected
    ):
        press(remote, 0x300, bytes([0x06, hue, 0x0C]) + u16(0))
        assert capture.names == [expected]

    def test_unknown_colour_byte_passes_through(self, remote, capture):
        press(remote, 0x300, bytes([0x30, 0x00, 0x2A, 0x08, 0x00]))
        assert capture.names == ["awox_color_press"]


class TestRefreshButtons:
    def test_refresh_short_press(self, remote, capture):
        press(remote, 8, bytes([0x10, 0x01, 0x01]))
        assert capture.names == ["refresh"]
        assert capture.params("refresh")["press"] == 1

    def test_refresh_short_press_alt_param(self, remote, capture):
        press(remote, 8, bytes([0x10, 0x00, 0x01]))
        assert capture.names == ["refresh"]

    def test_refresh_long_press(self, remote, capture):
        press(remote, 8, bytes([0x10, 0x01, 0x02]))
        assert capture.names == ["refresh_long"]
        assert capture.params("refresh_long")["press"] == 2

    def test_refresh_colored_short_via_enhanced_move_hue(self, remote, capture):
        press(remote, 0x300, bytes([0x41, 0x01]) + u16(12))
        assert capture.names == ["refresh_colored"]
        assert capture.params("refresh_colored")["press"] == 1

    def test_refresh_colored_long(self, remote, capture):
        press(remote, 0x300, bytes([0x41, 0x03]) + u16(12))
        assert capture.names == ["refresh_colored_long"]
        assert capture.params("refresh_colored_long")["press"] == 2

    def test_refresh_colored_short_via_move_hue(self, remote, capture):
        press(remote, 0x300, bytes([0x01, 0x01, 0x0C]))
        assert capture.names == ["refresh_colored"]


class TestDimmingButtons:
    @pytest.mark.parametrize("command", [0x02, 0x06])  # step, step_with_on_off
    def test_step_up(self, remote, capture, command):
        press(remote, 8, bytes([command, 0x00, 0x33]) + u16(0))
        assert capture.names == ["brightness_step_up"]

    @pytest.mark.parametrize("command", [0x02, 0x06])
    def test_step_down(self, remote, capture, command):
        press(remote, 8, bytes([command, 0x01, 0x33]) + u16(0))
        assert capture.names == ["brightness_step_down"]

    def test_move_up_via_with_on_off(self, remote, capture):
        press(remote, 8, bytes([0x04, 0xFE, 0x0A]) + u16(0))
        assert capture.names == ["brightness_move_up"]
        assert capture.params("brightness_move_up")["level"] == 254

    def test_move_down_plain(self, remote, capture):
        press(remote, 8, bytes([0x00, 0x01, 0x0A]) + u16(0))
        assert capture.names == ["brightness_move_down"]
        assert capture.params("brightness_move_down")["level"] == 1


class TestColourTemperatureButtons:
    def test_step_warm(self, remote, capture):
        press(remote, 0x300, bytes([0x4C, 0x01]) + u16(51) + u16(0) + u16(153) + u16(454))
        assert capture.names == ["color_temperature_step_down"]

    def test_step_cold(self, remote, capture):
        press(remote, 0x300, bytes([0x4C, 0x03]) + u16(51) + u16(0) + u16(153) + u16(454))
        assert capture.names == ["color_temperature_step_up"]

    def test_move_warm(self, remote, capture):
        press(remote, 0x300, bytes([0x0A]) + u16(454) + u16(0))
        assert capture.names == ["color_temperature_move_down"]
        assert capture.params("color_temperature_move_down")[
            "color_temp_mireds"
        ] == 454

    def test_move_cold(self, remote, capture):
        press(remote, 0x300, bytes([0x0A]) + u16(153) + u16(0))
        assert capture.names == ["color_temperature_move_up"]
        assert capture.params("color_temperature_move_up")[
            "color_temp_mireds"
        ] == 153


class TestFavouriteButtons:
    @pytest.mark.parametrize(("scene", "expected"), [(1, "recall_1"), (2, "recall_2")])
    def test_recall_short_press(self, remote, capture, scene, expected):
        press(remote, 5, bytes([0x05]) + u16(0x800A) + bytes([scene]))
        assert capture.names == [expected]

    @pytest.mark.parametrize(
        ("scene", "expected"), [(1, "recall_1_long"), (2, "recall_2_long")]
    )
    def test_store_long_press(self, remote, capture, scene, expected):
        # long press sends StoreScene (0x04) instead of RecallScene (0x05)
        press(remote, 5, bytes([0x04]) + u16(0x800A) + bytes([scene]))
        assert capture.names == [expected]


class TestTriggerCoverage:
    def test_trigger_count_and_keys(self, remote):
        triggers = remote.device_automation_triggers
        # 2 power + 6 colour + 2 refresh + 2 refresh_colored + 4 dim + 4 temp + 4 fav
        assert len(triggers) == 24

    def test_every_trigger_matches_cluster_and_endpoint(self, remote):
        cluster_ids = set(remote.endpoints[1].out_clusters)
        for (etype, subtype), descriptor in remote.device_automation_triggers.items():
            assert descriptor["endpoint_id"] == 1, (etype, subtype)
            assert descriptor["cluster_id"] in cluster_ids, (etype, subtype)
            assert descriptor["command"], (etype, subtype)

    def test_every_emitted_event_has_a_trigger(self, remote, capture):
        """Press every button and check the event maps to a declared trigger."""
        press_table = {
            "on": lambda: press(remote, 6, bytes([0x01])),
            "off": lambda: press(remote, 6, bytes([0x00])),
            "red": lambda: press(remote, 0x300, bytes([0x30, 0x00, 0xFF, 0x08, 0x00])),
            "red_long": lambda: press(remote, 0x300, bytes([0x06, 0xFF, 0x0C]) + u16(0)),
            "green": lambda: press(remote, 0x300, bytes([0x30, 0x00, 0x55, 0x08, 0x00])),
            "green_long": lambda: press(remote, 0x300, bytes([0x06, 0x55, 0x0C]) + u16(0)),
            "blue": lambda: press(remote, 0x300, bytes([0x30, 0x00, 0xAA, 0x08, 0x00])),
            "blue_long": lambda: press(remote, 0x300, bytes([0x06, 0xAA, 0x0C]) + u16(0)),
            "refresh": lambda: press(remote, 8, bytes([0x10, 0x01, 0x01])),
            "refresh_long": lambda: press(remote, 8, bytes([0x10, 0x01, 0x02])),
            "refresh_colored": lambda: press(remote, 0x300, bytes([0x41, 0x01]) + u16(12)),
            "refresh_colored_long": lambda: press(remote, 0x300, bytes([0x41, 0x03]) + u16(12)),
            "brightness_step_up": lambda: press(remote, 8, bytes([0x06, 0x00, 0x33]) + u16(0)),
            "brightness_step_down": lambda: press(remote, 8, bytes([0x06, 0x01, 0x33]) + u16(0)),
            "brightness_move_up": lambda: press(remote, 8, bytes([0x04, 0xFE, 0x0A]) + u16(0)),
            "brightness_move_down": lambda: press(remote, 8, bytes([0x00, 0x01, 0x0A]) + u16(0)),
            "color_temperature_step_up": lambda: press(
                remote, 0x300, bytes([0x4C, 0x03]) + u16(51) + u16(0) + u16(153) + u16(454)
            ),
            "color_temperature_step_down": lambda: press(
                remote, 0x300, bytes([0x4C, 0x01]) + u16(51) + u16(0) + u16(153) + u16(454)
            ),
            "color_temperature_move_up": lambda: press(
                remote, 0x300, bytes([0x0A]) + u16(153) + u16(0)
            ),
            "color_temperature_move_down": lambda: press(
                remote, 0x300, bytes([0x0A]) + u16(454) + u16(0)
            ),
            "recall_1": lambda: press(remote, 5, bytes([0x05]) + u16(0x800A) + bytes([1])),
            "recall_2": lambda: press(remote, 5, bytes([0x05]) + u16(0x800A) + bytes([2])),
            "recall_1_long": lambda: press(remote, 5, bytes([0x04]) + u16(0x800A) + bytes([1])),
            "recall_2_long": lambda: press(remote, 5, bytes([0x04]) + u16(0x800A) + bytes([2])),
        }

        declared_commands = {
            descriptor["command"] for descriptor in remote.device_automation_triggers.values()
        }

        for name, do_press in press_table.items():
            capture.events.clear()
            do_press()
            assert capture.names == [name], f"press for {name!r} emitted {capture.names}"
            assert name in declared_commands, f"event {name!r} has no device trigger"
