import re
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSER = "#chat-tab #le-composer"
COMPOSER_CONTAINERS = ".gradio-container " + COMPOSER + " :is("
CONTAINER_CLASSES = {".block", ".form", ".wrap", ".wrap-inner"}
NO_PAINT = {"transparent", "none", "unset", "initial", "inherit"}


def _split_selectors(text):
    selectors = []
    depth = 0
    current = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            selectors.append("".join(current))
            current = []
        else:
            current.append(char)
    selectors.append("".join(current))
    return [re.sub(r"\s+", " ", item).strip() for item in selectors if item.strip()]


def _css_rules(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [item for item in _split_selectors(block.group(1))
                     if not item.startswith("@")]
        if not selectors:
            continue
        declarations = {}
        for name, value in re.findall(r"([-a-zA-Z]+)\s*:\s*([^;]+)", block.group(2)):
            declarations[name.lower()] = re.sub(r"\s*!important\s*$", "", value).strip().lower()
        rules.append((selectors, declarations))
    return rules


def _merged_composer_rules():
    assets = ROOT / "learning_ext" / "assets"
    css = "\n".join((assets / name).read_text(encoding="utf-8")
                    for name in ("theme_layout.css", "refine.css"))
    return _css_rules(css)


def _last_paint_values(rules, target):
    background = shadow = None
    for selectors, declarations in rules:
        if not any(selector == target or selector.endswith(" " + target)
                   for selector in selectors):
            continue
        background = declarations.get("background",
                                      declarations.get("background-color", background))
        shadow = declarations.get("box-shadow", shadow)
    return background, shadow


def test_complete_stylesheet_resolves_base_and_page_image_urls():
    source = ast.parse((ROOT / "custom_app.py").read_text(encoding="utf-8"))
    function = next(node for node in source.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_presentation_stylesheet")
    namespace = {"Path": Path, "_HERE": str(ROOT)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "custom_app.py", "exec"), namespace)
    css = namespace["_presentation_stylesheet"]()
    assert "__ASSETS__" not in css
    assert "/file=" + (ROOT / "learning_ext/assets/coach-mascot.png").as_posix() in css


def test_learning_app_has_one_presentation_entry_and_no_html_duplicate():
    source = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")
    custom = (ROOT / "custom_app.py").read_text(encoding="utf-8")

    assert "css=self._css," in source
    assert "_presentation_stylesheet()" in custom
    assert "/le-presentation.css" in custom
    assert "add_api_route" in custom
    assert "_inject_css" not in source


def test_raw_template_only_contains_body_shell_and_floating_control_styles():
    source = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    block = source.split("def _presentation_stylesheet", 1)[1].split("return css", 1)[0]
    assets = re.findall(r'"([a-z_-]+\.css)"', block)

    assert assets == [
        "theme_tokens.css",
        "shell.css",
        "assistant.css",
        "text_polish.css",
        "theme_toggle.css",
    ]


def test_presentation_assets_are_unique_and_theme_layout_is_last():
    source = (ROOT / "learning_ext" / "presentation.py").read_text(encoding="utf-8")
    function = source.split("def presentation_css():", 1)[1].split("BRAND =", 1)[0]
    assets = re.findall(r'ASSETS / "([a-z_-]+\.css)"', function)
    page_layers = re.findall(r'for page_layer in \(([^)]+)\)', function)[0]
    layers = re.findall(r'"([a-z_]+)"', page_layers)

    assert len(assets) == len(set(assets))
    assert assets[-4:] == ["compact.css", "theme_layout.css", "refine.css", "refine_home.css"]
    assert "refine.css" in assets
    assert assets.index("refine.css") > assets.index("theme_layout.css")
    assert "dark_theme.css" not in assets
    assert layers[-6:] == ["refine_route", "refine_review", "refine_workbench",
                           "refine_settings", "refine_library", "refine_assistant"]
    for layer in layers:
        assert (ROOT / "learning_ext" / "assets" / f"{layer}.css").is_file()
    assert "onboarding.css" in assets
    assert "home.css" in assets
    assert "pages.css" in assets
    assert "selects.css" in assets


def test_theme_is_user_switchable_and_persistent():
    custom = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    js = (ROOT / "learning_ext" / "assets" / "theme_mode.js").read_text(encoding="utf-8")
    css = (ROOT / "learning_ext" / "assets" / "theme_toggle.css").read_text(encoding="utf-8")

    assert "theme_mode.js" in custom
    assert "__LE_ASSETS__" in custom
    assert "le.theme.mode" in js
    assert "dark_theme.css" in js
    assert "fetch(DARK_URL" in js
    assert "darkStyle.textContent" in js
    assert "localStorage.setItem" in js
    assert "role=\"menuitemradio\"" in js
    assert "prefers-color-scheme: dark" in js
    assert "addEventListener('storage'" in js
    assert "aria-checked" in js
    assert "var(--le-surface)" in css and "var(--le-ink)" in css
    assert "#le-theme-toggle" in css
    assert "prefers-reduced-motion: reduce" in css


def test_dark_theme_stays_neutral_and_layout_lives_in_theme_layout():
    dark = (ROOT / "learning_ext" / "assets" / "dark_theme.css").read_text(encoding="utf-8")
    layout = (ROOT / "learning_ext" / "assets" / "theme_layout.css").read_text(encoding="utf-8")
    tokens = (ROOT / "learning_ext" / "assets" / "theme_tokens.css").read_text(encoding="utf-8")

    assert "color-scheme: dark" in dark
    assert "#chat-tab #le-composer" not in dark
    assert "#chat-tab #le-composer .le-composer-tools" in layout
    assert "#chat-tab #le-chat-plus" in layout
    assert "#chat-tab .le-polish-tools" in layout
    assert "#le-chat-model-header #le-chat-model-trigger" in layout
    assert "coach-mascot-face.png" in layout
    assert "--le-surface" in layout and "--le-line" in layout
    assert "prefers-reduced-motion: reduce" in layout
    assert "html.le-dark:root" in tokens
    assert "--le-bg: #121213" in tokens
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", dark)
    assert "#e4eddf" not in tokens and "#e4eddf" not in dark
    assert "#35d8f7" not in tokens


def test_composer_inner_containers_stay_unpainted_after_layer_merge():
    rules = _merged_composer_rules()
    container_rules = []
    for selectors, declarations in rules:
        selected = {selector[len(COMPOSER_CONTAINERS):-1] for selector in selectors
                    if selector.startswith(COMPOSER_CONTAINERS) and selector.endswith(")")}
        if any({item.strip() for item in inner.split(",")} == CONTAINER_CLASSES
               for inner in selected):
            container_rules.append(declarations)

    assert container_rules, COMPOSER_CONTAINERS
    declarations = container_rules[-1]
    background = declarations.get("background", declarations.get("background-color"))
    assert background in {"transparent", "none"}
    assert declarations.get("border-color") == "transparent"
    assert declarations.get("box-shadow") in {"none", "unset", "initial"}


def test_last_composer_rule_keeps_input_area_unpainted():
    background, shadow = _last_paint_values(_merged_composer_rules(), COMPOSER)
    assert background is None or background in NO_PAINT
    assert shadow is None or shadow in NO_PAINT


def test_last_composer_focus_rule_adds_no_fill_or_shadow():
    background, shadow = _last_paint_values(_merged_composer_rules(), COMPOSER + ":focus-within")
    assert background is None or background in NO_PAINT
    assert shadow is None or shadow in NO_PAINT


def test_user_message_has_no_second_bubble_container():
    target = "#chat-tab #main-chat-bot .flex-wrap.user"
    rules = [declarations for selectors, declarations in _merged_composer_rules()
             if target in selectors]

    assert rules
    assert rules[-1].get("background") == "transparent"
    assert rules[-1].get("border") == "0"
    assert rules[-1].get("box-shadow") == "none"
