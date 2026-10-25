import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def test_coach_page_uses_real_lesson_engine_and_local_assets():
    app = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")
    custom = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    presentation = (ROOT / "learning_ext" / "presentation.py").read_text(encoding="utf-8")
    html = (ROOT / "learning_ext" / "coach.py").read_text(encoding="utf-8")

    assert "CoachLessonPage(self)" in app
    assert custom.count("assets/coach_lesson.js") == 1
    assert 'ASSETS / "coach_lesson.css"' in presentation
    assert 'id="coach-summary"' in html
    assert "练习进度保存在本机" in html
    assert "文字润色使用你配置的模型" in html
    assert "练习文字仅保存在本机" not in html
    assert "coach-mascot" in html


def test_lesson_engine_guards_duplicate_bindings_and_has_real_review():
    source = (ROOT / "learning_ext" / "assets" / "coach_lesson.js").read_text(encoding="utf-8")

    assert "staticBound" in source
    assert "coachBound" in source
    assert "localStorage.setItem(STORAGE_KEY" in source
    assert "function downloadReview()" in source
    assert "state.journal" in source
    assert "state.hintSteps.includes(3)" in source
    assert "const mountTimer = setInterval" in source
    assert "if ($('le-coach') && !$('coach-surface')?.hasChildNodes())" in source


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_all_lesson_validation_paths():
    source = (ROOT / "learning_ext" / "assets" / "coach_lesson.js").read_text(encoding="utf-8")
    source = source.replace("\n})();", "\n  globalThis.__coachTest = { validate };\n})();", 1)
    prelude = r"""
const document = {
  readyState: 'loading',
  addEventListener() {},
  getElementById() { return null; },
  querySelectorAll() { return []; },
};
const localStorage = { getItem() { return null; }, setItem() {} };
const setInterval = () => 0;
const setTimeout = () => 0;
const clearInterval = () => {};
"""
    scenario = r"""
validate = globalThis.__coachTest.validate;
const cells = { B1: 20, B2: 30, B3: 40 };
const results = {
  settingsOpen: validate('settings', 0, { night: true }),
  settingsClosed: validate('settings', 0, { night: false }),
  brightnessLow: validate('settings', 1, { night: true, brightness: 30 }),
  brightnessGood: validate('settings', 1, { night: true, brightness: 50 }),
  brightnessNightOff: validate('settings', 1, { night: false, brightness: 50 }),
  undoGood: validate('settings', 2, { night: false }),
  undoBad: validate('settings', 2, { night: true }),
  independentGood: validate('settings', 3, { night: false, brightness: 50 }),
  independentBad: validate('settings', 3, { night: true, brightness: 50 }),
  formulaAsNumber: validate('excel', 0, { formula: '90', cells }),
  formulaGood: validate('excel', 0, { formula: '=SUM(B1:B3)', cells }),
  formulaChanged: validate('excel', 1, { formula: '=SUM(B1:B3)', cells: { B1: 20, B2: 40, B3: 40 } }),
  formulaWrongChange: validate('excel', 1, { formula: '=SUM(B1:B3)', cells: { B1: 20, B2: 30, B3: 40 } }),
  formulaUndo: validate('excel', 2, { formula: '=SUM(B1:B3)', cells }),
  formulaIndependent: validate('excel', 3, { formula: '＝SUM（B1：B3）', cells }),
  goalShort: validate('agent', 0, { goal: '短', confirm: true, criteria: '' }),
  confirmOff: validate('agent', 1, { goal: '整理本周销售表并生成报告', confirm: false, criteria: '' }),
  criteriaShort: validate('agent', 2, { goal: '整理本周销售表并生成报告', confirm: true, criteria: '短' }),
  agentGood: validate('agent', 3, { goal: '整理本周销售表并生成报告', confirm: true, criteria: '字段完整且金额计算结果正确' }),
};
console.log(JSON.stringify(results));
"""
    completed = subprocess.run(
        [NODE, "-"],
        input=prelude + source + scenario,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    for key in (
        "settingsOpen",
        "brightnessGood",
        "undoGood",
        "independentGood",
        "formulaGood",
        "formulaChanged",
        "formulaUndo",
        "formulaIndependent",
        "agentGood",
    ):
        assert result[key]["ok"] is True, key
    for key in (
        "settingsClosed",
        "brightnessLow",
        "brightnessNightOff",
        "undoBad",
        "independentBad",
        "formulaAsNumber",
        "formulaWrongChange",
        "goalShort",
        "confirmOff",
        "criteriaShort",
    ):
        assert result[key]["ok"] is False, key
        assert result[key]["message"], key
