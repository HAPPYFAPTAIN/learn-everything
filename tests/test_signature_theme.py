from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = (ROOT / "learning_ext" / "assets" / "signature.css").read_text(encoding="utf-8")


def test_signature_theme_is_loaded_after_base_route_styles():
    source = (ROOT / "learning_ext" / "presentation.py").read_text(encoding="utf-8")
    raw = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    signature = '(ASSETS / "signature.css")'

    assert source.count(signature) == 1
    assert source.index('(ASSETS / "pages.css")') < source.index(signature)
    assert source.index('(ASSETS / "route.css")') < source.index(signature)
    assert "assets/signature.css" not in raw


def test_complete_font_stacks_and_numeric_roles_replace_thin_default():
    assert '--le-font: "Segoe UI Variable"' in THEME
    assert '"Microsoft YaHei UI"' in THEME
    assert '"Noto Sans CJK SC"' in THEME
    assert '--le-display:' in THEME
    assert '--le-num: "Bahnschrift"' in THEME
    assert "SiteSans" not in THEME
    assert "font-variant-numeric: tabular-nums" in THEME


def test_signature_navigation_and_open_function_headers_are_explicit():
    assert "@media (min-width: 801px)" in THEME
    assert "background: #103b4d !important" in THEME
    assert "box-shadow: inset 3px 0 #45d8e9 !important" in THEME
    assert ".gradio-container .le-editorial-head" in THEME
    assert "background: transparent !important" in THEME
    assert "ROUTE" in (ROOT / "learning_ext" / "page_design.py").read_text(encoding="utf-8")


def test_returning_home_stays_task_first_and_new_home_has_brand_scene():
    assert "#le-guided-home:not(:has(.le-resume-strip)) .le-discovery-hero" in THEME
    assert "#le-guided-home:has(.le-resume-strip) .le-discovery-hero" in THEME
    assert "display: none !important" in THEME
    assert "linear-gradient(120deg, #10384a, #16586b)" in THEME
    assert "@media (max-width: 800px)" in THEME
    assert "@media (prefers-reduced-motion: reduce)" in THEME


def test_decorative_microcopy_stays_out_of_primary_flow():
    from learning_ext import home_content
    from learning_ext.page_design import _PAGES

    assert [title for _, title in _PAGES.values()] == [
        "学习路线",
        "间隔复习",
        "查漏测验",
        "学习进展",
        "模型与连接",
        "资料库",
        "使用向导",
    ]
    assert "从今天感兴趣的事开始" not in home_content.HERO
    assert "le-card-art-label" not in home_content.direction_art("python")
    assert "le-card-art-stamp" not in home_content.direction_art("ai")
