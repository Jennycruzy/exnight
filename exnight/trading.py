"""Small execution adapter around Bitget's official Agent Hub CLI.

EXNIGHT keeps sizing and human confirmation locally, then delegates authenticated
account, order, status, and cancellation calls to ``bgc``. Agent Hub signs the
regular UTA v3 requests locally and supports Reality pairs through the standard
UTA order surface.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence


class AgentHubError(RuntimeError):
    """An Agent Hub command failed or returned an unusable response."""


def _coin_available(value: object, coin: str) -> str | None:
    """Find an available balance in the normalized or nested Agent Hub response."""
    if isinstance(value, Mapping):
        row_coin = str(value.get("coin", "")).upper()
        if row_coin == coin.upper():
            for key in ("available", "availableAmount", "availableBalance"):
                if value.get(key) is not None:
                    return str(value[key])
        for child in value.values():
            found = _coin_available(child, coin)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found = _coin_available(child, coin)
            if found is not None:
                return found
    return None


class AgentHubClient:
    """Thin, testable wrapper for the official ``bgc`` command."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        passphrase: str,
        *,
        executable: str | None = None,
        environment: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        timeout: float = 30.0,
    ):
        if not all((api_key, secret_key, passphrase)):
            raise ValueError("Bitget Agent Hub credentials are required")
        self.executable = executable or os.environ.get("AGENT_HUB_BIN", "bgc")
        self.environment = dict(environment or os.environ)
        self.environment.update({
            "BITGET_API_KEY": api_key,
            "BITGET_SECRET_KEY": secret_key,
            "BITGET_PASSPHRASE": passphrase,
        })
        if os.path.sep in self.executable:
            bin_dir = os.path.dirname(self.executable)
            path_parts = self.environment.get("PATH", "").split(os.pathsep)
            if bin_dir not in path_parts:
                self.environment["PATH"] = os.pathsep.join(
                    [bin_dir, *[part for part in path_parts if part]]
                )
        self.runner = runner or subprocess.run
        self.timeout = timeout

    def _call(self, args: list[str], *, dry_run: bool = False) -> dict:
        command = [self.executable, *args]
        if dry_run:
            command.append("--dry-run")
        try:
            result = self.runner(
                command,
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AgentHubError(
                f"Agent Hub CLI not found: {self.executable!r}; install @bitget-ai/bitget-agent-cli"
            ) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AgentHubError(f"Agent Hub command failed: {exc}") from exc

        output = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            raise AgentHubError(output[:1200] or f"Agent Hub exited with status {result.returncode}")
        try:
            payload = json.loads(output)
        except (TypeError, ValueError) as exc:
            raise AgentHubError("Agent Hub returned non-JSON output") from exc
        if not isinstance(payload, dict):
            raise AgentHubError("Agent Hub returned a non-object response")
        return payload

    def available(self, coin: str) -> str:
        payload = self._call(["account_overview", "--coin", coin, "--view", "full"])
        value = _coin_available(payload, coin)
        if value is None:
            raise AgentHubError(f"Agent Hub response did not contain an available {coin} balance")
        return value

    def place_limit(
        self,
        symbol: str,
        side: str,
        qty: str,
        price: str,
        client_oid: str,
        time_in_force: str,
        *,
        dry_run: bool = False,
    ) -> dict:
        return self._call([
            "order", "--action", "place", "--category", "SPOT", "--symbol", symbol,
            "--side", side, "--orderType", "limit", "--qty", qty, "--price", price,
            "--timeInForce", time_in_force, "--clientOid", client_oid,
        ], dry_run=dry_run)

    def order_info(self, order_id: str) -> dict:
        return self._call([
            "order", "--action", "detail", "--category", "SPOT", "--orderId", order_id,
        ])

    def cancel(self, symbol: str, order_id: str) -> dict:
        return self._call([
            "order", "--action", "cancel", "--category", "SPOT", "--symbol", symbol,
            "--orderId", order_id,
        ])
