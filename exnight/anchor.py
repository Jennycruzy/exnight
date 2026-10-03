"""Anchor frozen forward decisions on Arbitrum One.

A Git commit proves what the decision file said, but not when: commit timestamps are set by
the committer. This module puts a fingerprint of the frozen files into an Arbitrum One
transaction, whose block timestamp nobody can backdate. Anyone can then check that the
decision existed before the 20:00 ET sell cutoff.

What goes on chain (the transaction's calldata, plain UTF-8 so an explorer shows it):

    EXNIGHT v3 freeze
    commit <40-hex git commit>
    sha256 <64-hex> <repo-relative path>     (one line per frozen file)

The file hashes are computed from `git show <commit>:<path>`, i.e. the committed bytes, so a
later edit to a working-tree file can't change what was anchored. The transaction is a
zero-value self-transfer: it moves no funds, only records data.

Safety rules (each raises AnchorError, nothing is sent):
  - the RPC must report chain id 42161 (Arbitrum One mainnet);
  - the worst-case fee (gas limit x max fee per gas) must be under MAX_FEE_WEI;
  - the wallet must hold at least that worst-case fee;
  - after sending, the receipt must succeed and the on-chain calldata must equal the payload.

The private key is read from EXNIGHT_ANCHOR_KEY and is never printed or written anywhere.
Use a fresh wallet funded with about $1 of ETH and nothing else.

    python -m exnight.anchor verify data/anchors/anchor_v3_<stamp>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parent.parent
CHAIN_ID = 42161
DEFAULT_RPC = "https://arb1.arbitrum.io/rpc"
EXPLORER_TX = "https://arbiscan.io/tx/"
MAX_FEE_WEI = 10**14  # 0.0001 ETH, a few tens of cents; a normal anchor costs far less
HEADER = "EXNIGHT v3 freeze"
ET = ZoneInfo("America/New_York")


class AnchorError(RuntimeError):
    pass


def _git(*args: str, root: Path = ROOT) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def build_payload(commit: str, paths: list[str], root: Path = ROOT) -> str:
    """Text anchored on chain: the commit and the sha256 of each file as committed."""
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise AnchorError(f"not a full git commit hash: {commit!r}")
    if not paths:
        raise AnchorError("nothing to anchor")
    lines = [HEADER, f"commit {commit}"]
    for path in sorted(paths):
        blob = _git("show", f"{commit}:{path}", root=root)
        lines.append(f"sha256 {hashlib.sha256(blob).hexdigest()} {path}")
    return "\n".join(lines) + "\n"


def parse_payload(text: str) -> tuple[str, dict[str, str]]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] != HEADER or not lines[1].startswith("commit "):
        raise AnchorError("calldata is not an EXNIGHT anchor")
    files = {}
    for line in lines[2:]:
        tag, digest, path = line.split(" ", 2)
        if tag != "sha256":
            raise AnchorError(f"unexpected anchor line: {line!r}")
        files[path] = digest
    return lines[1].removeprefix("commit "), files


def next_cutoff(now: dt.datetime) -> dt.datetime:
    """The next 20:00 America/New_York at or after `now` (the EXIT sell cutoff)."""
    local = now.astimezone(ET)
    cutoff = local.replace(hour=20, minute=0, second=0, microsecond=0)
    if cutoff < local:
        cutoff += dt.timedelta(days=1)
    return cutoff.astimezone(dt.UTC)


class Rpc:
    def __init__(self, url: str, post: Callable[..., httpx.Response] | None = None):
        self.url = url
        self._post = post or httpx.post
        self._id = 0

    def __call__(self, method: str, *params):
        self._id += 1
        resp = self._post(self.url, json={"jsonrpc": "2.0", "id": self._id, "method": method,
                                          "params": list(params)}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise AnchorError(f"{method}: {body['error']}")
        return body["result"]


def anchor(payload: str, key: str, rpc: Rpc, *, send: bool, sleep: Callable[[float], None] = time.sleep,
           receipt_timeout_s: float = 180) -> dict:
    """Sign (and if `send`, broadcast and confirm) a zero-value self-transaction carrying `payload`."""
    from eth_account import Account

    chain = int(rpc("eth_chainId"), 16)
    if chain != CHAIN_ID:
        raise AnchorError(f"RPC is on chain {chain}, expected Arbitrum One ({CHAIN_ID})")
    account = Account.from_key(key)
    data = "0x" + payload.encode().hex()
    nonce = int(rpc("eth_getTransactionCount", account.address, "pending"), 16)
    gas_price = int(rpc("eth_gasPrice"), 16)
    estimate = int(rpc("eth_estimateGas", {"from": account.address, "to": account.address,
                                           "value": "0x0", "data": data}), 16)
    gas = estimate * 3 // 2
    max_fee = gas_price * 2
    worst = gas * max_fee
    if worst > MAX_FEE_WEI:
        raise AnchorError(f"worst-case fee {worst} wei exceeds cap {MAX_FEE_WEI} wei")
    tx = {"type": 2, "chainId": CHAIN_ID, "nonce": nonce, "to": account.address, "value": 0,
          "data": data, "gas": gas, "maxFeePerGas": max_fee, "maxPriorityFeePerGas": 0}
    signed = account.sign_transaction(tx)
    tx_hash = "0x" + signed.hash.hex().removeprefix("0x")
    out = {"chain_id": CHAIN_ID, "from": account.address, "nonce": nonce, "gas_limit": gas,
           "max_fee_per_gas": max_fee, "worst_case_fee_wei": worst, "tx_hash": tx_hash,
           "payload": payload, "sent": False}
    if not send:
        return out
    balance = int(rpc("eth_getBalance", account.address, "latest"), 16)
    if balance < worst:
        raise AnchorError(f"wallet {account.address} holds {balance} wei, needs {worst} wei")
    raw = signed.raw_transaction.hex()
    sent_hash = rpc("eth_sendRawTransaction", raw if raw.startswith("0x") else "0x" + raw)
    if sent_hash.lower() != tx_hash.lower():
        raise AnchorError(f"node returned hash {sent_hash}, signed {tx_hash}")
    out["sent"] = True
    deadline = time.monotonic() + receipt_timeout_s
    receipt = None
    while receipt is None:
        receipt = rpc("eth_getTransactionReceipt", tx_hash)
        if receipt is None:
            if time.monotonic() > deadline:
                raise AnchorError(f"no receipt for {tx_hash} after {receipt_timeout_s:.0f}s (it may still land)")
            sleep(2)
    if receipt.get("status") != "0x1":
        raise AnchorError(f"transaction {tx_hash} failed: status {receipt.get('status')}")
    onchain = rpc("eth_getTransactionByHash", tx_hash)
    if onchain["input"].lower() != data.lower():
        raise AnchorError("on-chain calldata differs from the payload")
    block = rpc("eth_getBlockByNumber", receipt["blockNumber"], False)
    ts = dt.datetime.fromtimestamp(int(block["timestamp"], 16), dt.UTC)
    out.update(block_number=int(receipt["blockNumber"], 16), block_time_utc=ts.isoformat(),
               fee_paid_wei=int(receipt["gasUsed"], 16) * int(receipt["effectiveGasPrice"], 16),
               explorer=EXPLORER_TX + tx_hash)
    return out


def verify(record: dict, rpc: Rpc, root: Path = ROOT) -> dict:
    """Re-check an anchor from the chain alone: calldata, block time, and committed file bytes."""
    tx = rpc("eth_getTransactionByHash", record["tx_hash"])
    if tx is None:
        raise AnchorError(f"transaction {record['tx_hash']} not found on chain {CHAIN_ID}")
    if int(rpc("eth_chainId"), 16) != CHAIN_ID:
        raise AnchorError("RPC is not Arbitrum One")
    text = bytes.fromhex(tx["input"].removeprefix("0x")).decode()
    commit, files = parse_payload(text)
    for path, digest in files.items():
        actual = hashlib.sha256(_git("show", f"{commit}:{path}", root=root)).hexdigest()
        if actual != digest:
            raise AnchorError(f"{path} at {commit[:12]} hashes to {actual}, anchor says {digest}")
    receipt = rpc("eth_getTransactionReceipt", record["tx_hash"])
    if receipt is None or receipt.get("status") != "0x1":
        raise AnchorError("transaction did not succeed")
    block = rpc("eth_getBlockByNumber", receipt["blockNumber"], False)
    ts = dt.datetime.fromtimestamp(int(block["timestamp"], 16), dt.UTC)
    return {"commit": commit, "files": sorted(files), "block_time_utc": ts.isoformat(),
            "block_number": int(receipt["blockNumber"], 16)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="re-check an anchor record against Arbitrum One")
    v.add_argument("record", type=Path)
    v.add_argument("--rpc", default=DEFAULT_RPC)
    args = ap.parse_args(argv)
    record = json.loads(args.record.read_text())
    result = verify(record, Rpc(args.rpc))
    cutoff = record.get("cutoff_utc")
    if cutoff and result["block_time_utc"] >= cutoff:
        print(f"FAIL: block time {result['block_time_utc']} is not before cutoff {cutoff}")
        return 1
    print(f"OK: commit {result['commit'][:12]} ({', '.join(result['files'])}) anchored in block "
          f"{result['block_number']} at {result['block_time_utc']}"
          + (f", before the {cutoff} cutoff" if cutoff else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
