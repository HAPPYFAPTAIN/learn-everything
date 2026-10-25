from learning_ext.upload_view import upload_feedback


def test_import_feedback_tracks_actual_results_and_hides_connection_tracebacks():
    html = upload_feedback("✅ | notes.pdf\n❌ | photo.webp: RetryError[Future raised APIConnectionError]", "Indexing [2/2]", ["notes.pdf", "photo.webp"])
    assert 'data-state="attention"' in html
    assert "已处理 2 份资料" in html
    assert "模型服务暂时连不上" in html
    assert "RetryError" not in html and "APIConnectionError" not in html
    assert "已加入，可用于知识问答" in html


def test_import_feedback_does_not_claim_completion_before_last_file_and_escapes_names():
    html = upload_feedback("✅ | <img onerror=x>.pdf", "Indexing [2/3]", [1, 2, 3])
    assert 'data-state="working"' in html
    assert "已完成 1 / 3 份" in html
    assert "<img" not in html and "&lt;img" in html
    assert 'data-state="attention"' in upload_feedback("", "Error: connection closed", [1])
