from pathlib import Path

from heatreserve.evidence import sha256_file, verify_manifest


def test_fixture_manifest_verifies(fixture_dir: Path) -> None:
    assert verify_manifest(fixture_dir) == []


def test_one_byte_mutation_breaks_manifest(tmp_path: Path, fixture_dir: Path) -> None:
    import shutil

    target = tmp_path / "fixture"
    shutil.copytree(fixture_dir, target)
    warning = target / "warning.json"
    warning.write_bytes(warning.read_bytes() + b" ")
    errors = verify_manifest(target)
    assert any(item.startswith("hash_mismatch:warning.json") for item in errors)


def test_raw_source_hash_is_reproducible(fixture_dir: Path) -> None:
    path = fixture_dir / "warning.json"
    assert sha256_file(path) == sha256_file(path)


def test_snapshot_binding_rejects_fixture_path_escape(fixture_dir: Path) -> None:
    from heatreserve.domain import SourceSnapshot
    from heatreserve.evidence import load_json, verify_snapshot_bindings

    payload = load_json(fixture_dir / "source_snapshots.json")
    original = SourceSnapshot.model_validate(payload["snapshots"][0])
    escaped = original.model_copy(update={"source_uri": "fixture://../warning.json"})
    errors = verify_snapshot_bindings(fixture_dir, (escaped,))
    assert errors == [f"snapshot_path_escape:{escaped.snapshot_id}"]


def test_episode_fixture_is_rebuilt_from_warning(fixture_dir: Path) -> None:
    from heatreserve.domain import HeatEpisode, Policy
    from heatreserve.episodes import build_episode_from_warning
    from heatreserve.evidence import load_json

    policy = Policy.model_validate(load_json(fixture_dir / "policy.json"))
    expected = HeatEpisode.model_validate(load_json(fixture_dir / "episode.json"))
    actual = build_episode_from_warning(
        load_json(fixture_dir / "warning.json"), policy,
        snapshot_id=expected.warning_snapshot_ids[0],
    )
    assert actual == expected


def test_malformed_manifest_reports_readiness_error(tmp_path: Path, fixture_dir: Path) -> None:
    import shutil

    target = tmp_path / "fixture-malformed-manifest"
    shutil.copytree(fixture_dir, target)
    (target / "manifest.json").write_text("{broken", encoding="utf-8")
    errors = verify_manifest(target)
    assert len(errors) == 1
    assert errors[0].startswith("manifest_error:")


def test_hourly_fact_must_bind_to_verified_weather_snapshot(service) -> None:
    from heatreserve.service import _validate_fact_sources

    snapshots = tuple(
        snapshot.model_copy(update={"verified": False})
        if snapshot.source_type == "hourly_weather" else snapshot
        for snapshot in service.fixtures.snapshots
    )
    import pytest
    with pytest.raises(ValueError, match="verified hourly_weather"):
        _validate_fact_sources(
            snapshots, service.fixtures.conditions, service.fixtures.cooling_points
        )


def test_cooling_fact_must_bind_to_cooling_snapshot(service) -> None:
    from heatreserve.service import _validate_fact_sources

    snapshots = tuple(
        snapshot.model_copy(update={"source_type": "other"})
        if snapshot.source_type == "cooling_points" else snapshot
        for snapshot in service.fixtures.snapshots
    )
    import pytest
    with pytest.raises(ValueError, match="verified cooling_points"):
        _validate_fact_sources(
            snapshots, service.fixtures.conditions, service.fixtures.cooling_points
        )
