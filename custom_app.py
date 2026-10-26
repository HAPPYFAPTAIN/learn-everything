"""学习 Agent 的启动入口。

替换 Kotaemon 默认的 app.py，使用 LearningApp 加载学习特化 Tab。
本地运行时通过 launcher.py 调用本文件。
"""

import os
import sys
from pathlib import Path

# Kotaemon 底座实例化 cohere/voyage 等 LLM 时会直接读 os.environ 校验 key，
# 本地若未配置这些服务，注入占位值避免启动崩溃 (实际不使用这些服务)
os.environ.setdefault("COHERE_API_KEY", "placeholder-key-1234567890")
os.environ.setdefault("VOYAGE_API_KEY", "placeholder-key-1234567890")
os.environ.setdefault("MISTRAL_API_KEY", "placeholder-key-1234567890")
os.environ.setdefault("GOOGLE_API_KEY", "placeholder-key-1234567890")

# 离线模式：避免启动时访问 huggingface.co 超时 (国内网络)；
# 需要下载模型时用户可手动设这两个变量为 0
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# NLTK 数据路径：指向 llama_index 自带的 nltk_cache，避免联网下载 stopwords/punkt
import sys as _sys  # noqa: E402

_NLTK_CACHE = os.path.join(
    os.path.dirname(_sys.executable),
    "..",
    "Lib",
    "site-packages",
    "llama_index",
    "core",
    "_static",
    "nltk_cache",
)
_NLTK_CACHE = os.path.normpath(_NLTK_CACHE)
if os.path.isdir(_NLTK_CACHE):
    os.environ["NLTK_DATA"] = _NLTK_CACHE

# 确保 learning_ext 在 import 路径中
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# Kotaemon 的 control.py 用 `import flowsettings`，要求 kotaemon 目录在 sys.path
_KOTAEMON_DIR = os.path.join(_HERE, "kotaemon")
sys.path.insert(0, _KOTAEMON_DIR)

from theflow.settings import settings as flowsettings  # noqa: E402


def _setup_file_logging() -> None:
    """把 WARNING 以上（含未捕获异常）写入文件，便于事后排查。

    之前 stdout 被重定向到文件时会带缓冲，Gradio 的堆栈根本落不了盘，
    出问题只能靠复现；这里显式落一个日志文件。
    """
    import logging  # noqa: WPS433

    app_data = getattr(flowsettings, "KH_APP_DATA_DIR", None)
    log_dir = (
        Path(app_data) / "logs"
        if app_data
        else Path(_HERE) / "kotaemon" / "ktem_app_data" / "logs"
    )
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
        )
        handler.setLevel(logging.WARNING)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        # Gradio 的异常默认只 print，挂到 root 上后同样会落盘
        logging.getLogger("gradio").addHandler(handler)
        logging.getLogger("learning_ext").addHandler(handler)
        # chromadb 的遥测报错是环境性噪音，屏蔽掉免得淹没真正的错误
        logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    except Exception as exc:  # 日志本身失败不应影响启动
        print(f"[learning_ext] 日志初始化失败: {exc}", flush=True)


_setup_file_logging()

KH_APP_DATA_DIR = getattr(flowsettings, "KH_APP_DATA_DIR", ".")
KH_GRADIO_SHARE = getattr(flowsettings, "KH_GRADIO_SHARE", False)
GRADIO_TEMP_DIR = os.getenv("GRADIO_TEMP_DIR", None)
if GRADIO_TEMP_DIR is None:
    GRADIO_TEMP_DIR = os.path.join(str(KH_APP_DATA_DIR), "gradio_tmp")
    os.environ["GRADIO_TEMP_DIR"] = GRADIO_TEMP_DIR

def _make_umap_optional() -> None:
    """umap 导入失败时放一个占位实现，避免整个应用起不来。

    背景：Kotaemon 的引用可视化模块在**模块级** `import umap`，而 umap 依赖
    numba → llvmlite。Windows 11 的「智能应用控制」(Smart App Control) 会把
    llvmlite.dll 判定为不受信任并直接拦掉（加载报 WinError 4551），于是
    ktem 一 import 就崩，整个 App 连启动都做不到。

    引用可视化只是「知识问答」里的一个附属图表，为它牺牲整个应用不值得。
    这里先试真 import，能用就用真的；不能用就塞一个占位模块，
    只让那一个功能在真正调用时报错，其余功能照常。
    """

    try:
        import umap  # noqa: F401,WPS433

        return
    except Exception as exc:  # noqa: BLE001
        import types

        print(f"[learning_ext] umap 不可用，已降级（引用可视化将不可用）：{exc}", flush=True)
        stub = types.ModuleType("umap")

        class UMAP:  # noqa: D401
            """占位：真正的 UMAP 依赖 llvmlite，被系统策略拦住了。"""

            def __init__(self, *args, **kwargs):
                raise RuntimeError(
                    "引用可视化需要 umap/numba，但 llvmlite 被系统策略拦截"
                    "（Windows 智能应用控制）。此功能暂不可用，其余功能不受影响。"
                )

        stub.UMAP = UMAP
        sys.modules["umap"] = stub


_make_umap_optional()

from learning_ext.app import LearningApp  # noqa: E402


def _presentation_stylesheet() -> str:
    """按需拼装全部样式：编辑 CSS 后刷新页面即可生效，不必重启进程。"""
    assets = Path(_HERE, "learning_ext", "assets")
    order = (
        "theme_tokens.css",
        "shell.css",
        "assistant.css",
        "text_polish.css",
        "theme_toggle.css",
    )
    css = "\n".join((assets / name).read_text(encoding="utf-8") for name in order)
    from learning_ext.presentation import presentation_css  # noqa: WPS433

    css += "\n" + presentation_css()
    return css.replace("__ASSETS__", "/file=" + assets.as_posix())


_PRESENTATION_CSS_URL = "/le-presentation.css"


def _register_presentation_route(routes_app) -> bool:
    """把样式挂到一条路由上，页面用 <link> 引用，刷新就拿到最新内容。"""
    try:
        from fastapi.responses import Response  # noqa: WPS433

        def stylesheet():
            return Response(
                _presentation_stylesheet(),
                media_type="text/css",
                headers={"Cache-Control": "no-store, max-age=0"},
            )

        routes_app.add_api_route(
            _PRESENTATION_CSS_URL, stylesheet, methods=["GET"], include_in_schema=False
        )
        return True
    except Exception as e:  # noqa: WPS433
        print(f"[learning_ext] stylesheet route failed: {e}", flush=True)
        return False


def _hook_presentation_route_into_gradio() -> None:
    """gradio 在 launch() 里会重建 FastAPI 实例，所以包一层 create_app。"""
    try:
        import gradio.routes as gradio_routes  # noqa: WPS433

        original = gradio_routes.App.create_app
        if getattr(original, "_le_route_hooked", False):
            return

        def create_app_with_styles(*args, **kwargs):
            created = original(*args, **kwargs)
            _register_presentation_route(created)
            from learning_ext.account.routes import register_account_routes
            register_account_routes(created)
            return created

        create_app_with_styles._le_route_hooked = True
        gradio_routes.App.create_app = staticmethod(create_app_with_styles)
    except Exception as e:  # noqa: WPS433
        print(f"[learning_ext] stylesheet hook failed: {e}", flush=True)


def _patch_gradio_template_for_learning_assets():
    """Insert learning_ext browser assets into Gradio's initial HTML template."""
    try:
        import gradio.routes as gradio_routes  # noqa: WPS433
        from jinja2 import ChoiceLoader, DictLoader  # noqa: WPS433

        script_path = "learning_ext/assets/word_lookup.js"
        word_lookup_js = Path(_HERE, script_path).read_text(encoding="utf-8")
        assets_base = "/file=" + Path(_HERE, "learning_ext", "assets").as_posix()
        theme_mode_js = Path(_HERE, "learning_ext/assets/theme_mode.js").read_text(encoding="utf-8")
        workspace_js = theme_mode_js.replace("__LE_ASSETS__", assets_base)
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/workspace.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/coach.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/coach_lesson.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/workbench.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/modal.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/outline.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/nav.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/assistant.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/onboarding.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/selects.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/pages.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/platforms.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/document_preview.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/consumer.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/settings_panels.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/chat_thinking.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/chat_streaming.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/chat_references.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/action_learning.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/rich_text.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/text_polish.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/motion.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/fullscreen_shell.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/route_browser.js").read_text(encoding="utf-8")
        script_tag = f"<script>\n{word_lookup_js}\n</script>"
        script_tag = f"<script>\n{workspace_js}\n</script>" + script_tag
        # 样式走 <link>：内容由 /le-presentation.css 每次请求重新拼装，
        # 改完 CSS 刷新页面就能看到，不必重启应用（也不会被 Gradio 改写选择器）。
        style_tag = f'<link rel="stylesheet" href="{_PRESENTATION_CSS_URL}">'
        # CSS 的 {# 和脚本中的模板字符应按原文输出，不能交给 Jinja 解析。
        browser_assets = "{% raw %}" + style_tag + "\n" + script_tag + "{% endraw %}"
        template_root = Path(gradio_routes.STATIC_TEMPLATE_LIB)
        overrides = {}
        for template_name in ("frontend/index.html", "frontend/share.html"):
            source = (template_root / template_name).read_text(encoding="utf-8")
            source = source.replace(
                "https://cdnjs.cloudflare.com/ajax/libs/iframe-resizer/4.3.1/iframeResizer.contentWindow.min.js",
                "/file=" + Path(_HERE, "learning_ext/assets/vendor/iframe-resizer/iframeResizer.contentWindow.min.js").as_posix(),
            )
            if script_path not in source:
                marker = '<script type="module" crossorigin src='
                if marker in source:
                    source = source.replace(marker, f"{browser_assets}\n\t\t{marker}", 1)
                else:
                    source = source.replace("</head>", f"\t\t{browser_assets}\n\t</head>", 1)
            overrides[template_name] = source

        original_loader = gradio_routes.templates.env.loader
        gradio_routes.templates.env.loader = ChoiceLoader(
            [DictLoader(overrides), original_loader]
        )
        gradio_routes.templates.env.cache.clear()
    except Exception as e:
        import traceback  # noqa: WPS433

        print(f"[learning_ext] template patch failed: {e}", flush=True)
        traceback.print_exc()


_patch_gradio_template_for_learning_assets()

from learning_ext.account.identity import require_local_desktop

require_local_desktop()
app = LearningApp()
_hook_presentation_route_into_gradio()
demo = app.make()
demo.queue()
demo.launch(
    favicon_path=app._favicon,
    inbrowser=False,
    prevent_thread_lock=False,
    allowed_paths=[
        "libs/ktem/ktem/assets",
        os.path.join(_HERE, "learning_ext", "assets"),
        GRADIO_TEMP_DIR,
    ],
    share=KH_GRADIO_SHARE,
)
