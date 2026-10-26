import gradio as gr

from learning_ext.rich_text import render_lesson

from gradio.events import Dependency

class LessonHTML(gr.HTML):
    is_template = True

    def postprocess(self, value):
        return render_lesson(value) if value is not None else None