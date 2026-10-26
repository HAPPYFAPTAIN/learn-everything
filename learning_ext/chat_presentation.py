from functools import wraps
from uuid import uuid4

import gradio as gr


def configure_chat_presentation(page):
    original = page.message_selected
    if getattr(original, "_learning_reference_selection", False):
        return

    @wraps(original)
    def message_selected(retrieval_history, plot_history, msg: gr.SelectData):
        content, plot = original(retrieval_history, plot_history, msg)
        if content is None or isinstance(content, str):
            marker = f"<!--le-reference-selection:{msg.index[0]}:{uuid4().hex}-->"
            content = (content or "") + marker
        return content, plot

    message_selected._learning_reference_selection = True
    page.message_selected = message_selected
