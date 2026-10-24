"""学习 Agent 的主 App。

继承 Kotaemon 的 App，在原 Tab 基础上插入学习特化 Tab：
    使用指南 | 快速配置 | 知识问答 | 学习路线 | 复习 | 测验 | 看板 | 资料库 | 帮助
"""

from __future__ import annotations

import logging

import gradio as gr
from decouple import config
from ktem.main import App as KotaemonApp
from theflow.settings import settings as flowsettings

logger = logging.getLogger(__name__)

KH_DEMO_MODE = getattr(flowsettings, "KH_DEMO_MODE", False)
KH_SSO_ENABLED = getattr(flowsettings, "KH_SSO_ENABLED", False)

from learning_ext.presentation import (
    BRAND,
    presentation_css,
    welcome_html,
    polish_chat_ui,
)


class LearningApp(KotaemonApp):
    """带学习特化功能的 Kotaemon App"""

    public_events = []

    def __init__(self):
        from learning_ext.optional_reranking import configure_optional_reranking

        from learning_ext.rag_requests import configure_rag_requests

        configure_rag_requests()
        configure_optional_reranking()
        super().__init__()
        try:
            from learning_ext.bootstrap import init_learning_ext

            init_learning_ext()
        except Exception as e:
            logger.warning(f"learning_ext 初始化延迟: {e} (将在首次使用时重试)")

    def _inject_css(self):
        try:
            gr.HTML("<style>" + presentation_css() + "</style>")
        except Exception:
            pass

    def make(self):
        markmap_js = """
        <script>
            window.markmap = {
                /** @type AutoLoaderOptions */
                autoLoader: {
                    toolbar: true, // Enable toolbar
                },
            };
        </script>
        """
        external_js = (
            "<script type='module' "
            "src='https://cdn.skypack.dev/pdfjs-viewer-element'>"
            "</script>"
            "<script type='module' "
            "src='https://cdnjs.cloudflare.com/ajax/libs/tributejs/5.1.3/tribute.min.js'></script>"
            f"{markmap_js}"
            "<script src='https://cdn.jsdelivr.net/npm/markmap-autoloader@0.16'></script>"
            "<script src='https://cdn.jsdelivr.net/npm/minisearch@7.1.1/dist/umd/index.min.js'></script>"
            "<link rel='stylesheet' href='https://cdnjs.cloudflare.com/ajax/libs/tributejs/5.1.3/tribute.css'/>"
        )

        with gr.Blocks(
            theme=self._theme,
            css=self._css + "\n" + presentation_css(),
            title="Learn Everything · 以太智元",
            analytics_enabled=False,
            js=self._js,
            head=external_js,
        ) as demo:
            self.app = demo
            self.settings_state.render()
            self.user_id.render()

            self.ui()

            self.declare_public_events()
            self.subscribe_public_events()
            self.register_events()
            self.on_app_created()

            demo.load(None, None, None, js=self._pdf_view_js)

        return demo

    def _build_quick_setup_tab(self, visible: bool):
        """极简模型配置页 (替换 Kotaemon 复杂的 Resources 页)"""
        from learning_ext.pages import QuickSetupPage

        with gr.Tab(
            "模型配置",
            elem_id="quick-setup-tab",
            id="quick-setup-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["quick-setup-tab"]:
            self.quick_setup_page = QuickSetupPage(self)
            self.quick_setup_page.on_building_ui()

    def _build_learning_tabs(self, visible: bool):
        from learning_ext.pages import (
            DashboardPage,
            PathGeneratorPage,
            QuizPage,
            ReviewPage,
            StudyWorkbenchPage,
        )

        with gr.Tab(
            "学习路线",
            elem_id="learning-path-tab",
            id="learning-path-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-path-tab"]:
            self.learning_path_page = PathGeneratorPage(self)
            self.learning_path_page.on_building_ui()

        with gr.Tab(
            "学习工作台",
            elem_id="learning-workbench-tab",
            id="learning-workbench-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-workbench-tab"]:
            self.learning_workbench_page = StudyWorkbenchPage(self)
            self.learning_workbench_page.on_building_ui()

        with gr.Tab(
            "间隔复习",
            elem_id="learning-review-tab",
            id="learning-review-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-review-tab"]:
            self.learning_review_page = ReviewPage(self)
            self.learning_review_page.on_building_ui()

        with gr.Tab(
            "查漏测验",
            elem_id="learning-quiz-tab",
            id="learning-quiz-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-quiz-tab"]:
            self.learning_quiz_page = QuizPage(self)
            self.learning_quiz_page.on_building_ui()

        with gr.Tab(
            "学习看板",
            elem_id="learning-dashboard-tab",
            id="learning-dashboard-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-dashboard-tab"]:
            self.learning_dashboard_page = DashboardPage(self)
            self.learning_dashboard_page.on_building_ui()

        with gr.Tab("动手学", elem_id="learning-coach-tab", id="learning-coach-tab", visible=visible,
                    elem_classes=["fill-main-area-height", "scrollable"]) as self._tabs["learning-coach-tab"]:
            from learning_ext.pages import CoachPage

            self.coach_page = CoachPage(self)
            self.coach_page.on_building_ui()

    def _build_guide_tab(self, visible: bool):
        from learning_ext.guide import GUIDE_MARKDOWN

        with gr.Tab(
            "学习首页",
            elem_id="learning-guide-tab",
            id="learning-guide-tab",
            visible=visible,
            elem_classes=["fill-main-area-height", "scrollable"],
        ) as self._tabs["learning-guide-tab"]:
            self.home_html = gr.HTML(welcome_html(self._has_any_course()))
            gr.HTML('<section class="le-start-guide"><div><h2>第一次用？跟着做就好。</h2><p>4 步认识学习流程，每次只看一步。</p></div><button data-le-tour-start>带我开始 →</button></section>')
            # 藏在屏幕外的刷新桥：切回「学习首页」时由 nav.js 点一下，
            # 重新判断有没有课程——没课程就不长「学习工作台」入口。
            # 用桥而不是 Tabs 事件：Gradio 4.44 的 Tab.select / Tabs.change 前端都不派发。
            with gr.Row(elem_id="le-home-bridge"):
                self.home_refresh = gr.Button("刷新首页", elem_id="le-home-refresh")
            self.home_refresh.click(
                self._refresh_home_cards,
                None,
                [self.home_html],
                show_progress="hidden",
            )

    def _has_any_course(self) -> bool:
        """库里有没有任何课程节点。查不到时按「有」处理，宁可不藏也不误藏。"""
        try:
            from sqlmodel import Session, select

            from ktem.db.engine import engine
            from learning_ext.db.models import KnowledgeNode

            with Session(engine) as s:
                return s.exec(select(KnowledgeNode).limit(1)).first() is not None
        except Exception:
            logger.warning("判断是否已有课程失败，按有课程处理", exc_info=True)
            return True

    def _refresh_home_cards(self):
        # 直接返回 HTML 字符串：gr.HTML 的新值就是这个字符串，
        # 用 gr.update(value=...) 在前端不生效（实测点了没反应）。
        has = self._has_any_course()
        return welcome_html(has)

    def _register_extra_events(self):
        for page_attr in (
            "quick_setup_page",
            "learning_path_page",
            "learning_workbench_page",
            "learning_review_page",
            "learning_quiz_page",
            "learning_dashboard_page",
            "coach_page",
        ):
            page = getattr(self, page_attr, None)
            if page is not None and hasattr(page, "on_register_events"):
                try:
                    page.on_register_events()
                except Exception as e:
                    logger.warning(f"{page_attr} 事件绑定失败: {e}")

    def ui(self):
        """重写 UI：精简 Tab 为中文 + 极简配置页替换复杂 Resources 页"""
        from ktem.pages.help import HelpPage
        from ktem.pages.setup import SetupPage
        from ktem.pages.chat import ChatPage

        KH_ENABLE_FIRST_SETUP_local = getattr(
            flowsettings, "KH_ENABLE_FIRST_SETUP", False
        )
        KH_APP_DATA_EXISTS_local = getattr(flowsettings, "KH_APP_DATA_EXISTS", True)
        if config("KH_FIRST_SETUP", default=False, cast=bool):
            KH_APP_DATA_EXISTS_local = False

        self._tabs = {}

        gr.HTML(BRAND, elem_id="le-brand-bar")
        with gr.Tabs(elem_id="le-app-tabs") as self.tabs:
            self._inject_css()

            vis = True

            # 1. 使用指南 (最先)
            self._build_guide_tab(visible=vis)
            # 2. 极简模型配置 (替换 Resources)
            self._build_learning_tabs(visible=vis)
            # 3. 知识问答
            with gr.Tab(
                "知识问答",
                elem_id="chat-tab",
                id="chat-tab",
                visible=vis,
                elem_classes=["fill-main-area-height", "scrollable"],
            ) as self._tabs["chat-tab"]:
                gr.HTML(
                    '<div class="le-page-heading"><div><p class="le-kicker">KNOWLEDGE / ASK</p><h1>知识问答</h1><p>带着问题阅读资料，找到有依据的答案。</p></div><div class="le-chat-tools"><button data-le-chat-panel="sources" aria-expanded="false">会话与资料</button><button data-le-chat-panel="evidence" aria-expanded="false">引用与来源</button></div></div>'
                )
                self.chat_page = ChatPage(self)
                polish_chat_ui(self)
            # 8. 资料库
            if len(self.index_manager.indices) == 1:
                for index in self.index_manager.indices:
                    with gr.Tab(
                        "资料库",
                        elem_id="indices-tab",
                        elem_classes=[
                            "fill-main-area-height",
                            "scrollable",
                            "indices-tab",
                        ],
                        id="indices-tab",
                        visible=vis and not KH_DEMO_MODE,
                    ) as self._tabs[f"{index.id}-tab"]:
                        setattr(self, f"_index_{index.id}", index.get_index_page_ui())
            elif len(self.index_manager.indices) > 1:
                with gr.Tab(
                    "资料库",
                    elem_id="indices-tab",
                    elem_classes=["fill-main-area-height", "scrollable", "indices-tab"],
                    id="indices-tab",
                    visible=vis and not KH_DEMO_MODE,
                ) as self._tabs["indices-tab"]:
                    for index in self.index_manager.indices:
                        with gr.Tab(
                            index.name, elem_id=f"{index.id}-tab"
                        ) as self._tabs[f"{index.id}-tab"]:
                            from importlib.util import find_spec
                            if type(index).__name__ == "GraphRAGIndex" and find_spec("graphrag") is None:
                                gr.Markdown("### 图谱资料暂不可用\n这个可选扩展的旧版依赖与当前环境不兼容。请使用「文件资料」进行资料问答，或使用已配置的「关联资料」建立知识关联。已有资料不会被删除。")
                            setattr(
                                self, f"_index_{index.id}", index.get_index_page_ui()
                            )
            from learning_ext.library_ui import polish_library_ui

            polish_library_ui(self)
            self._build_quick_setup_tab(visible=vis)
            # 9. 帮助
            with gr.Tab(
                "帮助",
                elem_id="help-tab",
                id="help-tab",
                visible=vis,
                elem_classes=["fill-main-area-height", "scrollable"],
            ) as self._tabs["help-tab"]:
                gr.HTML('<section class="le-start-guide"><div><h2>你想完成哪件事？</h2><p>选一个目标，跟着高亮区域操作。随时可以退出。</p></div><div class="le-guide-choices"><button data-le-tour-start="learning">创建路线与上课</button><button data-le-tour-start="review">复习、测验与进展</button><button data-le-tour-start="documents">上传资料并提问</button></div></section>')
                from learning_ext.guide import GUIDE_MARKDOWN
                with gr.Accordion("常见问题 · 需要时再看", open=False):
                    gr.Markdown(GUIDE_MARKDOWN)
                with gr.Accordion("关于与开源信息", open=False):
                    gr.Markdown("Learn Everything · 以太智元学习工作台。基于 [Kotaemon](https://github.com/Cinnamon/kotaemon) 构建资料问答，使用 FSRS 安排间隔复习。")

            if KH_ENABLE_FIRST_SETUP_local:
                with gr.Column(visible=False) as self.setup_page_wrapper:
                    self.setup_page = SetupPage(self)

        # 全局 AI 助教：建在 Tabs 之外，切换标签时面板与对话都不被重载
        from learning_ext.assistant import GlobalAssistant

        self.assistant_page = GlobalAssistant(self)
        self.assistant_page.on_building_ui()

    def on_subscribe_public_events(self):
        super().on_subscribe_public_events()

    def on_register_events(self):
        super().on_register_events()
