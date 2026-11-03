"""Tests for the quirk shim: decode, zone capture, and spurious-on handling.

Frames simulate the real remote (AwoX ERCU_3groups_Zm) end-to-end through
zigpy's packet pipeline, mirroring the live captures and the Zigbee2MQTT
eglo99099 converter.
"""

import collections
import importlib.util
import pathlib
import sys
from datetime import UTC, datetime
from unittest import mock

import pytest
import zigpy.device
import zigpy.listeners
import zigpy.types as t

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
QUIRK_PATH = REPO_ROOT / "custom_components" / "eglo_remote" / "quirk.py"

IEEE = t.EUI64.convert("a4:c1:38:19:fb:cd:41:6e")


def _load_quirk_module():
    """Load quirk.py standalone (the package __init__ imports Home Assistant)."""
    spec = importlib.util.spec_from_file_location("eglo_shim_under_test", QUIRK_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _MockApp:
    """Bare application stub: enough for Device init, matching and packets."""

    def __init__(self):
        self.devices = {}
        self.state = mock.Mock()
        self.state.node_info.nwk = t.NWK(0x0000)
        self.state.node_info.ieee = t.EUI64.convert("01:01:01:01:01:01:01:01")
        self.register_callback_listener = mock.Mock(return_value=mock.Mock())
        self.unregister_callback_listener = mock.Mock()
        self.add_listener = mock.Mock()
        self.remove_listener = mock.Mock()
        self._dblistener = None
        self._req_listeners = collections.defaultdict(list)


@pytest.fixture(scope="session")
def quirk_module():
    """Import the shim and drain zha-quirks' registry like ZHA does."""
    module = _load_quirk_module()

    import zhaquirks

    zhaquirks.setup()
    return module


def build_device_from_live_signature():
    """Build a zigpy device matching the remote's live ZHA signature."""
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

    app = _MockApp()
    device = zigpy.device.Device(app, IEEE, t.NWK(0xCDCE))
    device.manufacturer = "AwoX"
    device.model = "ERCU_3groups_Zm"
    device.node_desc = mock.Mock()
    device.node_desc.manufacturer_code = 4417

    ep1 = device.add_endpoint(1)
    ep1.profile_id = 260
    ep1.device_type = 2048  # 0x0800 COLOR_CONTROLLER
    for cluster_id in (
        Basic.cluster_id,
        Identify.cluster_id,
        Groups.cluster_id,
        LightLink.cluster_id,
    ):
        ep1.add_input_cluster(cluster_id)
    for cluster_id in (
        Basic.cluster_id,
        Identify.cluster_id,
        Groups.cluster_id,
        Scenes.cluster_id,
        OnOff.cluster_id,
        LevelControl.cluster_id,
        Color.cluster_id,
        LightLink.cluster_id,
    ):
        ep1.add_output_cluster(cluster_id)

    ep3 = device.add_endpoint(3)
    ep3.profile_id = 0x128F
    ep3.device_type = 2048
    for cluster_id in (0xFF50, 0xFF51):
        ep3.add_input_cluster(cluster_id)
        ep3.add_output_cluster(cluster_id)

    return device


class EventCapture:
    """zigpy cluster listener capturing `zha_send_event` calls."""

    def __init__(self):
        self.events = []

    def zha_send_event(self, command, args):
        self.events.append((command, args))

    @property
    def names(self):
        return [
            args["action"] for command, args in self.events if command == "eglo_action"
        ]

    def payloads(self):
        return [args for command, args in self.events if command == "eglo_action"]


@pytest.fixture
def remote(quirk_module):
    """A shim-applied remote ready to receive simulated button presses."""
    from zhaquirks.legacy import get_device

    device = build_device_from_live_signature()
    quirked = get_device(device)
    assert isinstance(quirked, quirk_module.EgloRemoteShim)
    # The packet debouncer needs a running event loop; duplicate filtering is
    # not what these tests exercise.
    quirked._should_filter_packet = lambda packet: False
    return quirked


@pytest.fixture
def capture(remote):
    """An EventCapture attached to every output cluster of endpoint 1."""
    cap = EventCapture()
    for cluster in remote.endpoints[1].out_clusters.values():
        cluster.add_listener(cap)
    return cap


def u16(value: int) -> bytes:
    return value.to_bytes(2, "little")


_counter = [0]


def press(
    remote,
    cluster_id: int,
    payload: bytes,
    zone: int | None = 1,
    *,
    group: int | None = None,
    expect_zone_change: bool = False,
) -> None:
    """Send a raw ZCL frame through the real packet pipeline.

    Unless `expect_zone_change` is set, the zone is pre-seeded as already
    known so the extra `zone_selected` action does not fire. `group`
    overrides the derived group address (for out-of-zone groups).
    """
    if zone is not None and not expect_zone_change:
        remote._eglo_last_zone = zone
    _counter[0] = (_counter[0] + 1) & 0xFF
    group_addr = (
        group if group is not None else (32777 + zone if zone is not None else None)
    )
    packet = t.ZigbeePacket(
        timestamp=datetime.now(tz=UTC),
        src=t.AddrModeAddress(addr_mode=t.AddrMode.IEEE, address=IEEE),
        src_ep=1,
        dst=t.AddrModeAddress(addr_mode=t.AddrMode.Group, address=group_addr),
        dst_ep=1,
        tsn=_counter[0],
        profile_id=260,
        cluster_id=cluster_id,
        data=t.SerializableBytes(bytes([0x11, _counter[0]]) + payload),
    )
    remote.packet_received(packet)


class TestShimResolution:
    def test_shim_matches_live_signature(self, quirk_module):
        from zhaquirks.legacy import get_device

        quirked = get_device(build_device_from_live_signature())
        assert isinstance(quirked, quirk_module.EgloRemoteShim)

    def test_other_model_does_not_match(self, quirk_module):
        from zhaquirks.legacy import get_device

        device = build_device_from_live_signature()
        device.model = "SomeOtherRemote"
        quirked = get_device(device)
        assert not isinstance(quirked, quirk_module.EgloRemoteShim)


class TestPowerButtons:
    def test_on_with_zone(self, remote, capture):
        press(remote, 6, bytes([0x01]), zone=2)
        assert capture.payloads() == [{"action": "on", "zone": 2}]

    def test_off(self, remote, capture):
        press(remote, 6, bytes([0x00]), zone=1)
        assert capture.payloads() == [{"action": "off", "zone": 1}]

    def test_spurious_on_after_colour_press_is_suppressed(self, remote, capture):
        press(remote, 0x300, bytes([0x30, 0x00, 0xFF, 0x08, 0x00]))
        press(remote, 6, bytes([0x01]))  # spurious on, <500ms later
        assert capture.names == ["red"]

    def test_on_after_window_is_kept(self, remote, capture):
        press(remote, 0x300, bytes([0x30, 0x00, 0x55, 0x08, 0x00]))
        remote._eglo_last_action_at -= 1.0
        press(remote, 6, bytes([0x01]))
        assert capture.names == ["green", "on"]


class TestColourButtons:
    @pytest.mark.parametrize(
        ("byte", "expected"),
        [
            (0xFF, "red"),
            (0xFE, "red"),
            (0x2A, "yellow"),
            (0x29, "yellow"),
            (0x55, "green"),
            (0x54, "green"),
            (0xAA, "blue"),
            (0xA9, "blue"),
        ],
    )
    def test_short_press_normalises_jitter(self, remote, capture, byte, expected):
        press(remote, 0x300, bytes([0x30, 0x00, byte, 0x08, 0x00]))
        assert capture.names == [expected]

    @pytest.mark.parametrize(
        ("hue", "expected"),
        [
            (0xFF, "red_long"),
            (0xFE, "red_long"),
            (0x55, "green_long"),
            (0xAA, "blue_long"),
        ],
    )
    def test_long_press_via_move_to_hue_and_saturation(
        self, remote, capture, hue, expected
    ):
        press(remote, 0x300, bytes([0x06, hue, 0x0C]) + u16(0))
        assert capture.names == [expected]

    def test_unknown_colour_byte_falls_through(self, remote, capture):
        press(remote, 0x300, bytes([0x30, 0x00, 0x01, 0x08, 0x00]))
        assert capture.names == []


class TestRefreshButtons:
    def test_refresh_short_press(self, remote, capture):
        press(remote, 8, bytes([0x10, 0x01, 0x01]))
        assert capture.names == ["refresh"]

    def test_refresh_long_press(self, remote, capture):
        press(remote, 8, bytes([0x10, 0x01, 0x02]))
        assert capture.names == ["refresh_long"]

    def test_refresh_colored_short_via_enhanced_move_hue(self, remote, capture):
        press(remote, 0x300, bytes([0x41, 0x01]) + u16(12))
        assert capture.names == ["refresh_colored"]

    def test_refresh_colored_long_via_enhanced_move_hue(self, remote, capture):
        press(remote, 0x300, bytes([0x41, 0x03]) + u16(12))
        assert capture.names == ["refresh_colored_long"]

    def test_refresh_colored_via_move_hue_rate_12(self, remote, capture):
        press(remote, 0x300, bytes([0x01, 0x01, 0x0C]))
        assert capture.names == ["refresh_colored"]


class TestDimmingButtons:
    def test_step_up(self, remote, capture):
        press(remote, 8, bytes([0x06, 0x00, 0x33]) + u16(0))
        assert capture.names == ["brightness_step_up"]

    def test_step_down(self, remote, capture):
        press(remote, 8, bytes([0x02, 0x01, 0x33]) + u16(0))
        assert capture.names == ["brightness_step_down"]

    def test_move_to_level(self, remote, capture):
        press(remote, 8, bytes([0x04, 0xFE, 0x0A]) + u16(0))
        assert capture.payloads() == [
            {"action": "brightness_move_to_level", "zone": 1, "level": 254}
        ]


class TestColourTemperatureButtons:
    def test_step_mode_1_is_up(self, remote, capture):
        """Live-verified: the remote's up button sends step_mode 1."""
        press(
            remote, 0x300, bytes([0x4C, 0x01]) + u16(51) + u16(0) + u16(153) + u16(454)
        )
        assert capture.names == ["color_temperature_step_up"]

    def test_step_mode_3_is_down(self, remote, capture):
        press(
            remote, 0x300, bytes([0x4C, 0x03]) + u16(51) + u16(0) + u16(153) + u16(454)
        )
        assert capture.names == ["color_temperature_step_down"]

    def test_move_to_color_temp(self, remote, capture):
        press(remote, 0x300, bytes([0x0A]) + u16(454) + u16(0))
        assert capture.payloads() == [
            {
                "action": "color_temperature_move",
                "zone": 1,
                "color_temperature": 454,
            }
        ]


class TestFavouriteButtons:
    @pytest.mark.parametrize(("scene", "expected"), [(1, "recall_1"), (2, "recall_2")])
    def test_recall(self, remote, capture, scene, expected):
        press(remote, 5, bytes([0x05]) + u16(0x800A) + bytes([scene]))
        assert capture.names == [expected]

    @pytest.mark.parametrize(
        ("scene", "expected"), [(1, "recall_1_long"), (2, "recall_2_long")]
    )
    def test_store(self, remote, capture, scene, expected):
        press(remote, 5, bytes([0x04]) + u16(0x800A) + bytes([scene]))
        assert capture.names == [expected]


class TestZoneTracking:
    def test_zone_from_group_address(self, remote, capture):
        press(remote, 6, bytes([0x01]), zone=3)
        assert capture.payloads() == [{"action": "on", "zone": 3}]

    def test_zone_selected_emitted_on_change(self, remote, capture):
        press(remote, 6, bytes([0x01]), zone=1)
        capture.events.clear()
        press(remote, 6, bytes([0x01]), zone=3, expect_zone_change=True)
        assert capture.names == ["zone_selected", "on"]
        assert capture.payloads()[0] == {"action": "zone_selected", "zone": 3}

    def test_out_of_zone_group_clears_zone(self, remote, capture):
        press(remote, 6, bytes([0x01]), zone=1)
        capture.events.clear()
        press(remote, 6, bytes([0x01]), group=100)
        assert capture.payloads() == [{"action": "on"}]
