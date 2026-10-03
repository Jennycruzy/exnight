import datetime as dt
import hashlib
import subprocess

import pytest

from exnight import anchor

KEY = "0x" + "11" * 32  # throwaway test key, never funded


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.csv").write_text("event,verdict\nx,HOLD\n")
    subprocess.run(["git", "add", "a.csv"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "m"],
                   cwd=tmp_path, check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                            capture_output=True, text=True).stdout.strip()
    return commit


class FakeChain:
    def __init__(self, chain_id=anchor.CHAIN_ID, gas_price=10**7, balance=10**16, status="0x1", tamper=False):
        self.chain_id, self.gas_price, self.balance, self.status, self.tamper = chain_id, gas_price, balance, status, tamper
        self.calls = []

    def __call__(self, method, *params):
        self.calls.append(method)
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getTransactionCount":
            return "0x5"
        if method == "eth_gasPrice":
            return hex(self.gas_price)
        if method == "eth_estimateGas":
            self.data = params[0]["data"]
            return hex(30_000)
        if method == "eth_getBalance":
            return hex(self.balance)
        if method == "eth_sendRawTransaction":
            from eth_utils import keccak
            self.hash = "0x" + keccak(bytes.fromhex(params[0][2:])).hex()
            return self.hash
        if method == "eth_getTransactionReceipt":
            return {"status": self.status, "blockNumber": "0x10", "gasUsed": hex(25_000),
                    "effectiveGasPrice": hex(self.gas_price)}
        if method == "eth_getTransactionByHash":
            return {"input": self.data + ("00" if self.tamper else "")}
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(1_791_000_000)}
        raise AssertionError(method)


def test_payload_hashes_committed_bytes_not_working_tree(tmp_path):
    commit = _repo(tmp_path)
    (tmp_path / "a.csv").write_text("edited after the freeze\n")
    text = anchor.build_payload(commit, ["a.csv"], tmp_path)
    digest = hashlib.sha256(b"event,verdict\nx,HOLD\n").hexdigest()
    assert text == f"EXNIGHT v3 freeze\ncommit {commit}\nsha256 {digest} a.csv\n"
    assert anchor.parse_payload(text) == (commit, {"a.csv": digest})


def test_payload_rejects_short_commit_and_empty_list(tmp_path):
    commit = _repo(tmp_path)
    with pytest.raises(anchor.AnchorError):
        anchor.build_payload(commit[:12], ["a.csv"], tmp_path)
    with pytest.raises(anchor.AnchorError):
        anchor.build_payload(commit, [], tmp_path)


def test_dry_run_signs_but_never_broadcasts():
    chain = FakeChain()
    out = anchor.anchor("EXNIGHT v3 freeze\ncommit x\n", KEY, chain, send=False)
    assert out["sent"] is False and out["chain_id"] == 42161 and out["tx_hash"].startswith("0x")
    assert "eth_sendRawTransaction" not in chain.calls and "eth_getBalance" not in chain.calls


def test_refuses_wrong_chain():
    with pytest.raises(anchor.AnchorError, match="expected Arbitrum One"):
        anchor.anchor("p", KEY, FakeChain(chain_id=421614), send=True)


def test_refuses_fee_above_cap():
    with pytest.raises(anchor.AnchorError, match="exceeds cap"):
        anchor.anchor("p", KEY, FakeChain(gas_price=10**12), send=True)


def test_refuses_underfunded_wallet_before_sending():
    chain = FakeChain(balance=1)
    with pytest.raises(anchor.AnchorError, match="needs"):
        anchor.anchor("p", KEY, chain, send=True)
    assert "eth_sendRawTransaction" not in chain.calls


def test_send_confirms_receipt_and_calldata():
    chain = FakeChain()
    out = anchor.anchor("EXNIGHT v3 freeze\ncommit x\n", KEY, chain, send=True, sleep=lambda s: None)
    assert out["sent"] and out["tx_hash"] == chain.hash and out["block_number"] == 16
    assert out["fee_paid_wei"] == 25_000 * 10**7 and out["explorer"].endswith(chain.hash)


def test_send_fails_on_reverted_or_tampered_tx():
    with pytest.raises(anchor.AnchorError, match="failed"):
        anchor.anchor("p", KEY, FakeChain(status="0x0"), send=True, sleep=lambda s: None)
    with pytest.raises(anchor.AnchorError, match="differs"):
        anchor.anchor("p", KEY, FakeChain(tamper=True), send=True, sleep=lambda s: None)


def test_next_cutoff_is_2000_new_york():
    # 23:30 UTC on 6 Oct 2026 is 19:30 EDT -> cutoff 00:00 UTC on 7 Oct
    now = dt.datetime(2026, 10, 6, 23, 30, tzinfo=dt.UTC)
    assert anchor.next_cutoff(now) == dt.datetime(2026, 10, 7, 0, 0, tzinfo=dt.UTC)
    # after the cutoff it rolls to the next evening
    late = dt.datetime(2026, 10, 7, 1, 0, tzinfo=dt.UTC)
    assert anchor.next_cutoff(late) == dt.datetime(2026, 10, 8, 0, 0, tzinfo=dt.UTC)
