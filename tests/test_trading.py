import json
import subprocess

from exnight.trading import AgentHubClient, AgentHubError


def fake_runner(output: dict, *, returncode: int = 0, seen: list | None = None):
    def run(command, **kwargs):
        if seen is not None:
            seen.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode, json.dumps(output), "")

    return run


def test_agent_hub_place_uses_standard_uta_order_surface_without_exposing_credentials():
    seen = []
    client = AgentHubClient(
        "key", "secret", "pass", executable="bgc", environment={"PATH": "/bin"},
        runner=fake_runner({"endpoint": "POST /api/v3/trade/place-order", "data": {"orderId": "1"}}, seen=seen),
    )
    out = client.place_limit("RAVGOUSDT", "buy", "1", "100", "exnight-test", "ioc")
    assert out["data"]["orderId"] == "1"
    command, kwargs = seen[0]
    assert command == [
        "bgc", "order", "--action", "place", "--category", "SPOT", "--symbol", "RAVGOUSDT",
        "--side", "buy", "--orderType", "limit", "--qty", "1", "--price", "100",
        "--timeInForce", "ioc", "--clientOid", "exnight-test",
    ]
    assert kwargs["env"]["BITGET_API_KEY"] == "key"
    assert "secret" not in command
    assert "pass" not in command


def test_agent_hub_available_reads_nested_account_snapshot():
    client = AgentHubClient(
        "key", "secret", "pass", runner=fake_runner({
            "data": {"assets": [{"coin": "USDT", "available": "12"}]},
        }),
    )
    assert client.available("USDT") == "12"


def test_agent_hub_dry_run_is_forwarded_to_cli():
    seen = []
    client = AgentHubClient(
        "key", "secret", "pass", runner=fake_runner({"data": {"dryRun": True}}, seen=seen),
    )
    client.place_limit("RAVGOUSDT", "sell", "1", "100", "exnight-test", "fok", dry_run=True)
    assert seen[0][0][-1] == "--dry-run"


def test_absolute_agent_hub_path_adds_its_node_directory_to_path():
    seen = []
    client = AgentHubClient(
        "key", "secret", "pass", executable="/opt/node/bin/bgc", environment={"PATH": "/bin"},
        runner=fake_runner({"data": {}}, seen=seen),
    )
    client.order_info("1")
    assert seen[0][1]["env"]["PATH"] == "/opt/node/bin:/bin"


def test_agent_hub_rejects_non_json_cli_output():
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "not-json", "")

    client = AgentHubClient("key", "secret", "pass", runner=run)
    try:
        client.order_info("1")
    except AgentHubError as exc:
        assert "non-JSON" in str(exc)
    else:
        raise AssertionError("expected AgentHubError")
