from inspect import signature
import re

import gradio as gr
from gradio.helpers import special_args
import pytest

from learning_ext.chat_presentation import configure_chat_presentation


MARKER = re.compile(r"<!--le-reference-selection:(\d+):([0-9a-f]{32})-->$")


class Page:
    def __init__(self):
        self.calls = []

    def message_selected(self, retrieval_history, plot_history, msg: gr.SelectData):
        self.calls.append((retrieval_history, plot_history, msg))
        index = msg.index[0]
        try:
            return retrieval_history[index], plot_history[index]
        except IndexError:
            return gr.update(), None


def selection(index):
    return gr.SelectData(None, {"index": [index, 1], "value": "answer", "selected": True})


def test_identical_source_selections_get_distinct_completion_markers():
    page = Page()
    configure_chat_presentation(page)
    source = '<details class="evidence"><summary>Source</summary><p>Text</p></details>'
    history = [source, source]
    plots = [None, {"data": [1, 2]}]
    event = selection(1)

    first, plot = page.message_selected(history, plots, event)
    second, _ = page.message_selected(history, plots, event)

    first_marker = MARKER.search(first)
    second_marker = MARKER.search(second)
    assert first_marker and second_marker
    assert first_marker.group(1) == second_marker.group(1) == "1"
    assert first_marker.group(2) != second_marker.group(2)
    assert first[:first_marker.start()] == second[:second_marker.start()] == source
    assert history == [source, source]
    assert plot is plots[1]
    assert all(call[0] is history and call[1] is plots and call[2] is event for call in page.calls)


@pytest.mark.parametrize("content", [None, ""])
def test_empty_evidence_still_reports_selection_completion(content):
    page = Page()
    configure_chat_presentation(page)
    history = [content]
    result, plot = page.message_selected(history, [None], selection(0))

    assert MARKER.fullmatch(result)
    assert history == [content]
    assert plot is None


def test_gradio_updates_pass_through_without_changes():
    page = Page()
    configure_chat_presentation(page)
    update = gr.update(visible=False)
    content, plot = page.message_selected([update], [None], selection(0))

    assert content is update
    assert content == {"__type__": "update", "visible": False}
    assert plot is None
    missing, plot = page.message_selected([], [], selection(0))
    assert missing == gr.update()
    assert plot is None


def test_wrapper_preserves_gradio_event_injection_and_is_idempotent():
    page = Page()
    original = page.message_selected
    configure_chat_presentation(page)
    wrapper = page.message_selected
    configure_chat_presentation(page)

    assert page.message_selected is wrapper
    assert signature(wrapper) == signature(original)
    assert wrapper.__annotations__["msg"] is gr.SelectData
    assert wrapper.__wrapped__ == original

    history = ["<p>First</p>", "<p>Second</p>"]
    plots = [None, None]
    inputs, progress_index, event_index = special_args(
        wrapper, [history, plots], event_data=selection(1)
    )
    assert progress_index is None
    assert event_index == 2
    assert isinstance(inputs[2], gr.SelectData)
    assert inputs[2].index == [1, 1]
    content, plot = wrapper(*inputs)
    assert content.startswith("<p>Second</p><!--le-reference-selection:1:")
    assert content.count("<!--le-reference-selection:") == 1
    assert plot is None


def test_original_selection_errors_are_preserved():
    class BrokenPage:
        def message_selected(self, retrieval_history, plot_history, msg: gr.SelectData):
            raise RuntimeError("selection failed")

    page = BrokenPage()
    configure_chat_presentation(page)
    with pytest.raises(RuntimeError, match="selection failed"):
        page.message_selected([], [], selection(0))
