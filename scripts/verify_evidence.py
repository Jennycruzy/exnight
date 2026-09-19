"""Verify saved source, depth-manifest, and AI-evidence hashes offline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_ledger(path: Path) -> list[str]:
    from exnight.events import CorporateAction
    errors = []
    seen = set()
    try:
        with path.open() as stream:
            for number, line in enumerate(stream, 1):
                try:
                    event = CorporateAction.model_validate_json(line)
                    if event.event_id in seen:
                        errors.append(f"duplicate event ID {event.event_id}: {path}:{number}")
                    seen.add(event.event_id)
                except ValueError:
                    errors.append(f"invalid ledger row: {path}:{number}")
        if not seen:
            errors.append(f"empty ledger: {path}")
    except OSError as exc:
        errors.append(f"unreadable ledger {path}: {exc}")
    return errors


def verify_sources(root: Path) -> list[str]:
    from exnight.sources import SOURCES
    errors = []
    for source in SOURCES.values():
        if not source.path.exists():
            errors.append(f"missing source: {source.path}")
        elif sha256(source.path) != source.sha256:
            errors.append(f"source hash mismatch: {source.key}")
    return errors


def verify_depth_manifests(root: Path) -> list[str]:
    errors = []
    for manifest_path in sorted((root / "data" / "raw" / "depth").glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
            for entry in manifest["files"]:
                path = manifest_path.parent / entry["path"]
                if not path.exists():
                    errors.append(f"missing depth file: {path}")
                elif path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
                    errors.append(f"depth hash mismatch: {path}")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid depth manifest {manifest_path}: {exc}")
    return errors


def verify_ai_records(root: Path) -> list[str]:
    errors = []
    for record_path in sorted((root / "data" / "raw" / "ai_confounder").glob("*/*.json")):
        try:
            record = json.loads(record_path.read_text())
            prompt = record.get("prompt")
            expected = record.get("prompt_sha256")
            if prompt is not None and expected != hashlib.sha256(prompt.encode()).hexdigest():
                errors.append(f"AI prompt hash mismatch: {record_path}")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"invalid AI record {record_path}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify EXNIGHT evidence hashes without network access")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = verify_sources(args.root) + verify_depth_manifests(args.root) + verify_ai_records(args.root)
    for path in sorted((args.root / "data" / "ledger").glob("*.jsonl")):
        errors.extend(verify_ledger(path))
    report = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    print(json.dumps(report, indent=1))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
