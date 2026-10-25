from learning_ext.library_ui import friendly_chunk_panel


def test_preview_localizes_controls_without_changing_document_text():
    body = '[Page 1] (text) This is the original document.'
    markup = '<details><summary>[1/2] [Page 1] <span style="opacity:0.7">(text)</span> A title</summary>' + body + '</details>'
    header, result = friendly_chunk_panel(lambda: ('**2 chunks** (1 text, 1 thumbnail)', markup))()
    assert header == '### 内容预览 · 2 项'
    assert '第 1 页' in result
    assert '正文' in result
    assert result.endswith(body + '</details>')
    assert ' A title</summary>' in result


def test_preview_handles_missing_page_and_empty_selection():
    assert friendly_chunk_panel(lambda: ('', ''))() == ('', '')
    markup = '<summary>[1/1] <span>(table)</span> Table title</summary>'
    _, result = friendly_chunk_panel(lambda: ('**1 chunks** (1 table)', markup))()
    assert '片段 1' in result
    assert '表格' in result
    assert 'Table title' in result


def test_library_adapter_accepts_unstyled_native_components():
    from types import SimpleNamespace
    from learning_ext.library_ui import polish_library_ui

    page = SimpleNamespace(
        filter=SimpleNamespace(elem_classes=None),
        upload_progress_panel=SimpleNamespace(elem_classes=None),
    )
    app = SimpleNamespace(
        app=SimpleNamespace(blocks={}),
        index_manager=SimpleNamespace(indices=[SimpleNamespace(id=1)]),
        _index_1=page,
    )
    polish_library_ui(app)
    assert page.filter.elem_classes == ["le-library-search"]
    assert page.upload_progress_panel.elem_classes == ["le-library-progress"]
    assert page.filter.lines == page.filter.max_lines == 1


def test_chat_model_names_preserve_backend_ids_without_exposing_connection_details():
    from learning_ext.presentation import chat_model_choices

    choices = chat_model_choices({
        "openai": {"default": True, "spec": {"model": "glm-example", "api_key": "secret", "base_url": "private-endpoint"}},
        "local": {"spec": {"model_name": "qwen-example"}},
    })
    assert choices == [("glm-example · 默认", "(default)"), ("glm-example · openai", "openai"), ("qwen-example · local", "local")]
    assert "secret" not in str(choices)
    assert "private-endpoint" not in str(choices)
    assert chat_model_choices({}) == [("默认模型", "(default)")]

