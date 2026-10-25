from __future__ import annotations

import html

import gradio as gr


FIELDS = {
    "onboarding_page.topic": "goal",
    "onboarding_page.background": "background",
    "learning_path_page.topic_input": "goal",
    "learning_path_page.background_input": "background",
    "learning_path_page.goal_input": "goal",
    "learning_workbench_page.add_title": "title",
    "learning_workbench_page.add_desc": "instruction",
    "learning_workbench_page.note_input": "note",
    "learning_workbench_page.gate_ans1": "answer",
    "learning_workbench_page.gate_ans2": "answer",
    "learning_workbench_page.gate_ans3": "answer",
    "learning_workbench_page.recite_input": "answer",
    "learning_workbench_page.adapt_panel.note": "feedback",
    "learning_workbench_page.action_learning.question": "question",
    "learning_review_page.front": "question",
    "learning_review_page.back": "answer",
    "learning_quiz_page.answer": "answer",
    "assistant_page.chat_input": "question",
    "chat_page.chat_panel.text_input": "question",
    "chat_page.chat_control.conversation_rn": "title",
    "chat_page.report_issue.more_detail": "feedback",
    "coach_page.desktop_goal": "goal",
    "coach_page.input": "question",
}


def mark_fields(app):
    marked = []
    fields = dict(FIELDS)
    for name in vars(app):
        if name.startswith("_index_") and getattr(getattr(app, name), "group_name", None) is not None:
            fields[f"{name}.group_name"] = "title"
    for path, kind in fields.items():
        component = app
        for name in path.split("."):
            component = getattr(component, name, None)
            if component is None:
                break
        if component is None:
            continue
        classes = list(component.elem_classes or [])
        for value in ("le-polishable", f"le-polish-kind-{kind}"):
            if value not in classes:
                classes.append(value)
        component.elem_classes = classes
        marked.append(path)
    return marked


class TextPolishUI:
    def __init__(self, app):
        self.app = app

    def build(self):
        mark_fields(self.app)
        with gr.Column(elem_id="le-polish-bridge"):
            self.request = gr.Textbox(value="", show_label=False, elem_id="le-polish-request")
            self.trigger = gr.Button("润色请求", elem_id="le-polish-trigger")
            self.result = gr.HTML("", elem_id="le-polish-result")
        return self

    def register(self):
        self.trigger.click(
            self.run,
            inputs=self.request,
            outputs=self.result,
            concurrency_id="text-polish",
            concurrency_limit=2,
            show_progress="hidden",
            api_name=False,
        )

    @staticmethod
    def run(payload):
        from learning_ext.text_polish.service import polish_request

        return '<pre data-le-polish-response>' + html.escape(polish_request(payload)) + '</pre>'
