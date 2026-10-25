from __future__ import annotations

import gradio as gr
from ktem.app import BasePage

from learning_ext.agent.desktop_coach import DesktopCoach
from learning_ext.coach import coach_html


class CoachLessonPage(BasePage):
    def on_building_ui(self):
        self.desktop = DesktopCoach()
        self.lesson_root = gr.HTML(coach_html())
        self.desktop_mode = gr.Button("桌面实操入口", visible=False, elem_id="le-desktop-mode")
        with gr.Column(visible=False, elem_id="le-desktop-coach") as self.desktop_panel:
            gr.HTML(
                '<div class="le-desktop-head"><span>DESKTOP PRACTICE</span>'
                '<h2>桌面实操</h2><p>只操作独立练习器，不控制其他应用。</p></div>'
            )
            with gr.Row(elem_id="le-desktop-actions"):
                self.desktop_launch = gr.Button("1. 启动练习器", variant="primary")
                self.desktop_observe = gr.Button("2. 读取控件")
                self.desktop_type = gr.Button("3. 输入任务文字")
                self.desktop_check = gr.Button("4. 点击检查")
                self.desktop_undo = gr.Button("5. 撤销")
                self.desktop_close = gr.Button("结束并关闭", variant="secondary")
            self.desktop_goal = gr.Textbox(
                label="任务文字",
                value="整理本周销售表并生成汇总报告",
                lines=2,
            )
            self.desktop_approve = gr.Checkbox(
                label="允许当前步骤操作这个测试窗口",
                value=False,
            )
            self.desktop_status = gr.Markdown("先启动独立练习器。", elem_id="le-desktop-status")
            self.desktop_log = gr.Textbox(
                label="观察与操作记录",
                lines=12,
                interactive=False,
                elem_id="le-desktop-log",
            )
            self.desktop_back = gr.Button("返回其他练习", size="sm")

    def _outputs(self):
        return [self.desktop_status, self.desktop_log, self.desktop_approve]

    @staticmethod
    def _wrap(result):
        message = result["message"]
        details = result.get("details") or ""
        return message, details, False

    def on_register_events(self):
        self.desktop_mode.click(
            lambda: (gr.update(visible=False), gr.update(visible=True)),
            outputs=[self.lesson_root, self.desktop_panel],
        )
        self.desktop_back.click(
            self._desktop_back,
            outputs=[self.lesson_root, self.desktop_panel, self.desktop_status, self.desktop_log, self.desktop_approve],
        )
        self.desktop_launch.click(self._launch, inputs=self.desktop_approve, outputs=self._outputs())
        self.desktop_observe.click(self._observe, outputs=self._outputs())
        self.desktop_type.click(
            self._type,
            inputs=[self.desktop_goal, self.desktop_approve],
            outputs=self._outputs(),
        )
        self.desktop_check.click(self._check, inputs=self.desktop_approve, outputs=self._outputs())
        self.desktop_undo.click(self._undo, inputs=self.desktop_approve, outputs=self._outputs())
        self.desktop_close.click(self._close, outputs=self._outputs())

    def _launch(self, approved):
        return self._wrap(self.desktop.launch(approved))

    def _observe(self):
        return self._wrap(self.desktop.observe())

    def _type(self, goal, approved):
        return self._wrap(self.desktop.type_goal(goal, approved))

    def _check(self, approved):
        return self._wrap(self.desktop.check(approved))

    def _undo(self, approved):
        return self._wrap(self.desktop.undo(approved))

    def _close(self):
        return self._wrap(self.desktop.close())

    def _desktop_back(self):
        if self.desktop.step < 6:
            self.desktop.close()
        self.desktop.step = 0
        self.desktop.window_title = ""
        return gr.update(visible=True), gr.update(visible=False), "已返回其他练习", "", False
