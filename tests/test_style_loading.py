import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_learning_app_has_one_presentation_entry_and_no_html_duplicate():
    source = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")

    assert 'css=self._css + "\\n" + presentation_css()' in source
    assert "_inject_css" not in source


def test_raw_template_only_contains_body_shell_and_floating_control_styles():
    source = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    block = source.split("raw_css = ", 1)[1].split("raw_css = raw_css.replace", 1)[0]
    assets = re.findall(r'learning_ext/assets/([a-z_-]+\.css)', block)

    assert assets == ["shell.css", "assistant.css", "text_polish.css"]


def test_presentation_assets_are_unique_and_component_polish_is_last():
    source = (ROOT / "learning_ext" / "presentation.py").read_text(encoding="utf-8")
    function = source.split("def presentation_css():", 1)[1].split("BRAND =", 1)[0]
    assets = re.findall(r'ASSETS / "([a-z_-]+\.css)"', function)

    assert len(assets) == len(set(assets))
    assert assets[-4:] == ["signature.css", "consumer.css", "settings_panels.css", "compact.css"]
    assert "onboarding.css" in assets
    assert "home.css" in assets
    assert "pages.css" in assets
    assert "selects.css" in assets
