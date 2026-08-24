from miru_server.config import ServerConfig
from miru_server.discovery import should_advertise


def test_only_lan_bound_server_is_advertised():
    assert should_advertise(ServerConfig(host="0.0.0.0")) is True
    assert should_advertise(ServerConfig(host="192.168.1.10")) is True
    assert should_advertise(ServerConfig(host="127.0.0.1")) is False
    assert should_advertise(ServerConfig(host="localhost")) is False


def test_advertising_can_be_disabled():
    assert should_advertise(
        ServerConfig(host="0.0.0.0", advertise_lan=False)
    ) is False
