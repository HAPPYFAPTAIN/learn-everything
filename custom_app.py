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


def _patch_gradio_template_for_learning_assets():
    """Insert learning_ext browser assets into Gradio's initial HTML template."""
    try:
        import gradio.routes as gradio_routes  # noqa: WPS433
        from jinja2 import ChoiceLoader, DictLoader  # noqa: WPS433

        script_path = "learning_ext/assets/word_lookup.js"
        word_lookup_js = Path(_HERE, script_path).read_text(encoding="utf-8")
        workspace_js = Path(_HERE, "learning_ext/assets/workspace.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/coach.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/workbench.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/outline.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/nav.js").read_text(encoding="utf-8")
        workspace_js += "\n" + Path(_HERE, "learning_ext/assets/assistant.js").read_text(encoding="utf-8")
        script_tag = f"<script>\n{word_lookup_js}\n</script>"
        script_tag = f"<script>\n{workspace_js}\n</script>" + script_tag
        # 助教面板、悬浮球与外壳修正都作用于容器之外（body 级 / .gradio-container），
        # 走 gr.Blocks(css=...) 会被 Gradio 加上 .contain 前缀而失效，故用原始 style 注入
        raw_css = Path(_HERE, "learning_ext/assets/shell.css").read_text(encoding="utf-8")
        raw_css += "\n" + Path(_HERE, "learning_ext/assets/assistant.css").read_text(encoding="utf-8")
        # 与 presentation_css() 共用 __ASSETS__ 占位符：助教头像等图片走 Gradio 的 /file= 静态路径
        raw_css = raw_css.replace(
            "__ASSETS__", "/file=" + Path(_HERE, "learning_ext", "assets").as_posix()
        )
        style_tag = f"<style>\n{raw_css}\n</style>"
        template_root = Path(gradio_routes.STATIC_TEMPLATE_LIB)
        overrides = {}
        for template_name in ("frontend/index.html", "frontend/share.html"):
            source = (template_root / template_name).read_text(encoding="utf-8")
            if script_path not in source:
                marker = '<script type="module" crossorigin src='
                if marker in source:
                    source = source.replace(marker, f"{style_tag}\n\t\t{script_tag}\n\t\t{marker}", 1)
                else:
                    source = source.replace("</head>", f"\t\t{style_tag}\n\t\t{script_tag}\n\t</head>", 1)
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

app = LearningApp()
demo = app.make()
demo.queue().launch(
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
