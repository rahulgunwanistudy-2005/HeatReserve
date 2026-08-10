import urllib.request


def test_judge_mode_requires_no_network(monkeypatch, service) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in judge replay")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    result = service.run_judge_demo()
    assert result["receipt_verification"]["valid"] is True


def test_reset_reproduces_same_core_outputs(service) -> None:
    first = service.run_judge_demo()
    second = service.run_judge_demo()
    assert first["commitment"]["commitment_id"] == second["commitment"]["commitment_id"]
    assert first["commitment"]["decision"] == second["commitment"]["decision"]
    assert first["plan"].model_dump(mode="json") == second["plan"].model_dump(mode="json")
    assert first["receipt"].model_dump(mode="json") == second["receipt"].model_dump(mode="json")
    assert first["allocator"] == second["allocator"]
