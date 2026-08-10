from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import SourceSnapshot


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    sha256: str
    media_type: str
    evidence_class: str
    source_uri: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load JSON fixture {path}: {exc}") from exc


def load_manifest(fixture_dir: Path) -> tuple[ManifestEntry, ...]:
    manifest_path = fixture_dir / "manifest.json"
    payload = load_json(manifest_path)
    entries = []
    for item in payload.get("files", []):
        entries.append(ManifestEntry(**item))
    if not entries:
        raise ValueError(f"Fixture manifest contains no files: {manifest_path}")
    return tuple(entries)


def verify_manifest(fixture_dir: Path) -> list[str]:
    errors: list[str] = []
    fixture_root = fixture_dir.resolve()
    try:
        entries = load_manifest(fixture_dir)
    except (TypeError, ValueError) as exc:
        return [f"manifest_error:{exc}"]
    for entry in entries:
        path = (fixture_dir / entry.path).resolve()
        if path != fixture_root and fixture_root not in path.parents:
            errors.append(f"path_escape:{entry.path}")
            continue
        if not path.is_file():
            errors.append(f"missing:{entry.path}")
            continue
        actual = sha256_file(path)
        if actual != entry.sha256:
            errors.append(f"hash_mismatch:{entry.path}:{actual}")
    return errors


def require_verified_manifest(fixture_dir: Path) -> None:
    errors = verify_manifest(fixture_dir)
    if errors:
        raise ValueError("Fixture manifest verification failed: " + "; ".join(errors))


def verify_snapshot_bindings(fixture_dir: Path, snapshots: tuple[SourceSnapshot, ...]) -> list[str]:
    errors: list[str] = []
    fixture_root = fixture_dir.resolve()
    for snapshot in snapshots:
        uri = snapshot.source_uri
        if not uri.startswith("fixture://"):
            continue
        relative = uri.removeprefix("fixture://")
        path = (fixture_dir / relative).resolve()
        if path != fixture_root and fixture_root not in path.parents:
            errors.append(f"snapshot_path_escape:{snapshot.snapshot_id}")
            continue
        if not path.is_file():
            errors.append(f"snapshot_missing:{snapshot.snapshot_id}:{relative}")
            continue
        actual = sha256_file(path)
        if actual != snapshot.raw_sha256:
            errors.append(f"snapshot_hash_mismatch:{snapshot.snapshot_id}:{relative}")
    return errors
