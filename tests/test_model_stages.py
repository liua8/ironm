"""按任务选模型（spec [2026-10-23] §142）：管家的后台决策单独一个环节，没配时沿用作答。不调用真实模型。"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

from ironm_agent import next_targets, review
from ironm_agent.llm import MODELS_PATH, ModelsConfig, Reply, load_models
from tests.fakes import FakeLLM
from tests.test_next_targets import HARD, squat
from tests.test_next_targets import setup as next_setup
from tests.test_review import setup as review_setup

ROOT = Path(__file__).resolve().parents[1]


def test_coach_falls_back_to_expert_when_not_configured() -> None:
    raw = load_models().model_dump()
    raw["stages"].pop("coach")
    raw["stages"]["expert"]["model"] = "作答用的"
    old = ModelsConfig.model_validate(raw)
    assert old.route("coach").model == "作答用的" and old.route("expert").model == "作答用的"
    assert load_models(MODELS_PATH).route("coach").model == "deepseek-flash"  # 默认不变


def test_checkup_and_next_targets_use_the_coach_stage() -> None:
    stages: list[str] = []

    def answer(stage: Any, *_: Any) -> Reply:
        stages.append(stage)
        return Reply('{"summary": "都正常"}')

    asyncio.run(review.run("42", review_setup(), FakeLLM(answer)))
    asyncio.run(next_targets.run("42", next_setup(squat(4), HARD), FakeLLM(answer), HARD))
    assert stages and set(stages) == {"coach"}


def test_reports_record_models_without_keys(tmp_path: Path) -> None:
    import json

    from evals.replay.report import Row, save

    spec = importlib.util.spec_from_file_location("replay_script", ROOT / "scripts" / "replay.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = load_models().model_dump()
    raw["stages"]["coach"]["model"] = "deepseek-v4-pro"
    raw["stages"]["coach"]["extra_body"] = {"thinking": {"type": "enabled"}}
    used = mod.models_used(ModelsConfig.model_validate(raw))
    assert used["coach"] == "deepseek-v4-pro（思考）" and used["expert"] == "deepseek-flash"
    path = save([Row(case="a", turn=1, say="x")], "", tmp_path, meta={"models": used})
    body = json.loads(path.read_text())
    assert body["meta"]["models"]["coach"] == "deepseek-v4-pro（思考）"
    assert "api_key" not in path.read_text() and "DEEPSEEK" not in path.read_text()
