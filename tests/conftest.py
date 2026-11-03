"""Shared fixtures: register quirks once and build a device from the real signature."""

import importlib.util
import pathlib
import sys
from unittest import mock

import pytest
import zigpy.device
import zigpy.types as t

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
QUIRK_PATH = (
    REPO_ROOT / "custom_components" / "eglo_connect_z_remote" / "quirk.py"
)

IEEE = t.EUI64.convert("a4:c1:38:19:fb:cd:41:6e")


def _load_quirk_module():
    """Load quirk.py standalone (the package __init__ imports Home Assistant)."""
    spec = importlib.util.spec_from_file_location(
        "eglo_connect_z_quirk_under_test", QUIRK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _MockApp:
    """Bare application stub: enough for Device init and quirk matching."""

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


@pytest.fixture(scope="session")
def quirk_module():
    """Import the quirk and drain zha-quirks' registry like ZHA does."""
    module = _load_quirk_module()

    import zhaquirks  # noqa: PLC0415

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
        return [name for name, _ in self.events]

    def params(self, name):
        for command, args in self.events:
            if command == name:
                return args.as_dict() if args is not None else {}
        raise AssertionError(f"event {name!r} was not emitted")


@pytest.fixture
def remote(quirk_module):
    """A quirk-applied remote ready to receive simulated button presses."""
    from zhaquirks.legacy import get_device

    device = build_device_from_live_signature()
    quirked = get_device(device)
    assert isinstance(quirked, quirk_module.EgloConnectZRemote)
    return quirked


@pytest.fixture
def capture(remote):
    """An EventCapture attached to every output cluster of endpoint 1."""
    cap = EventCapture()
    for cluster in remote.endpoints[1].out_clusters.values():
        cluster.add_listener(cap)
    return cap


def press(remote, cluster_id: int, payload: bytes, tsn: int = 0x21) -> None:
    """Feed a raw ZCL frame (frame control 0x11) into the quirk's cluster."""
    cluster = remote.endpoints[1].out_clusters[cluster_id]
    data = bytes([0x11, tsn, payload[0]]) + payload[1:]
    hdr, cmd = cluster.deserialize(data)
    cluster.handle_message(hdr, cmd)
