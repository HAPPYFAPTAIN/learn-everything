from functools import wraps
import re


def friendly_chunk_panel(original):
    @wraps(original)
    def wrapped(*args, **kwargs):
        header, markup = original(*args, **kwargs)
        match = re.match(r"\*\*(\d+) chunks\*\*", header)
        if match:
            header = f"### 内容预览 · {match[1]} 项"
        names = {"text": "正文", "table": "表格", "image": "图片", "thumbnail": "页面预览"}
        def prefix(match):
            page = f"第 {match[4]} 页" if match[4] else f"片段 {match[2]}"
            return f'{match[1]}<span class="le-preview-page">{page}</span><span class="le-preview-kind">{names[match[5]]}</span> '
        markup = re.sub(r'(<summary[^>]*>)\[(\d+)/(\d+)\](?: \[Page ([0-9]+)\])? <span[^>]*>\((text|table|image|thumbnail)\)</span> ', prefix, markup)
        return header, markup
    return wrapped


def polish_library_ui(app):
    labels = {
        "File Collection": "文件资料", "GraphRAG Collection": "图谱资料 · 可选扩展",
        "LightRAG Collection": "关联资料 · 可选扩展", "Upload Files": "上传文件",
        "Use Web Links": "导入网页", "Input web URLs": "网页地址",
        "Advanced indexing options": "更新已有资料", "Force reindex file": "重新解析已上传的文件",
        "Upload result": "处理结果", "Upload info": "处理进度", "Files": "文件",
        "Groups": "资料集", "Filter by name:": "搜索文件名称", "Advance options": "更多操作",
        "Chunk type": "内容类型", "Group name": "资料集名称", "File": "文件",
    }
    values = {
        "Upload and Index": "加入资料库", "## Upload Progress": "## 正在整理资料",
        "Clear Upload Info and Close": "收起处理结果", "Go to Chat": "使用此资料提问",
        "Download": "导出解析内容", "Delete": "删除", "Close": "收起详情",
        "Download all files": "导出全部解析内容", "Delete all files": "删除全部资料",
        "Confirm delete": "确认删除", "Cancel": "取消", "(separated by new line)": "每行填写一个网页地址。",
        "Selected file: (please select above)": "选择上方文件，查看正文片段与来源。",
    }
    for block in app.app.blocks.values():
        label = getattr(block, "label", None)
        if isinstance(label, str) and label in labels:
            block.label = labels[label]
            if label == "Advanced indexing options":
                block.elem_classes = [*(block.elem_classes or []), "le-import-options"]
        if getattr(block, "info", None) == "(1) Case-insensitive. (2) Search with empty string to show all files.":
            block.info = "输入名称筛选，留空显示全部文件。"
        value = getattr(block, "value", None)
        if isinstance(value, str):
            if value in values:
                block.value = values[value]
            elif value.startswith("- Supported file types:"):
                from html import escape
                lines = value.replace("Supported file types:", "支持格式：").replace("Maximum file size:", "单个文件上限：").replace("Maximum number of files:", "文件数量上限：")
                block.value = '<details class="le-file-requirements"><summary>支持的格式与大小</summary><p>' + '<br>'.join(escape(line.lstrip('- ')) for line in lines.splitlines()) + '</p></details>'

    from functools import wraps

    def localized_download(original):
        @wraps(original)
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            button = result[-1] if isinstance(result, tuple) else result
            if getattr(button, "label", None) == "Start download":
                button.label = "点击下载解析内容"
                button._constructor_args[0]["label"] = button.label
            elif getattr(button, "label", None) == "Download":
                button.label = "导出解析内容"
                button._constructor_args[0]["label"] = button.label
            return result
        return wrapped

    for index in app.index_manager.indices:
        page = getattr(app, f"_index_{index.id}", None)
        if page is None:
            continue
        if hasattr(page, "selected_file_id"):
            from learning_ext.document_preview import attach_preview
            attach_preview(app, page, index)
        for name, css in {
            "selection_info": "le-source-selection", "selected_panel": "le-source-title",
            "chunk_header": "le-source-summary", "chunk_toolbar": "le-source-filter",
            "chunks": "le-source-chunks", "chat_button": "le-source-chat",
            "download_single_button": "le-source-download",
            "group_list": "le-source-groups",
        }.items():
            component = getattr(page, name, None)
            if component is not None:
                component.elem_classes = [*(component.elem_classes or []), css]
        for name, title in {"group_add_button": "新建资料集", "group_save_button": "保存资料集", "group_chat_button": "围绕资料集提问", "group_close_button": "收起", "group_delete_button": "删除资料集"}.items():
            component = getattr(page, name, None)
            if component is not None:
                component.value = title
        if hasattr(page, "filter"):
            page.filter.label = "查找资料"
            page.filter.info = None
            page.filter.placeholder = "搜索资料名称…"
            page.filter.lines = 1
            page.filter.max_lines = 1
            page.filter.elem_classes = [*(page.filter.elem_classes or []), "le-library-search"]
        if hasattr(page, "upload_progress_panel"):
            page.upload_progress_panel.elem_classes = [*(page.upload_progress_panel.elem_classes or []), "le-library-progress"]
            if hasattr(page, "upload_result") and hasattr(page, "upload_info"):
                from learning_ext.upload_view import attach_upload_feedback
                attach_upload_feedback(page)
        if hasattr(page, "files"):
            page.files.label = "添加文件"
            extra_types = [".webp", ".bmp", ".gif", ".odt", ".rtf"]
            page._supported_file_types = list(dict.fromkeys([*page._supported_file_types, *extra_types]))
            page.files.file_types = page._supported_file_types
            page._index.config["supported_file_types"] = ", ".join(page._supported_file_types)
        if hasattr(page, "chat_button"):
            page.chat_button.value = "围绕这份资料提问 →"
            page.chat_button.variant = "primary"
        if hasattr(page, "selected_panel_true"):
            page.selected_panel_true = "### {name}"
        if hasattr(page, "chunk_type_filter"):
            page.chunk_type_filter.choices = [("全部内容", "all"), ("正文", "text"), ("表格", "table"), ("图片", "image"), ("页面预览", "thumbnail")]
        if hasattr(page, "_build_chunk_panel"):
            page._build_chunk_panel = friendly_chunk_panel(page._build_chunk_panel)
        from importlib.util import find_spec
        if type(index).__name__ == "GraphRAGIndex" and find_spec("graphrag") is None:
            for name in ("upload_button", "files", "urls"):
                control = getattr(page, name, None)
                if control is not None:
                    control.interactive = False
                    control._constructor_args[0]["interactive"] = False
            page.upload_button.value = "扩展暂不可用"
            page.upload_button._constructor_args[0]["value"] = "扩展暂不可用"

        for name in ("download_single_button", "download_all_button"):
            button = getattr(page, name, None)
            if button is not None:
                button.label = "导出全部解析内容" if name == "download_all_button" else "导出解析内容"
                button._constructor_args[0]["label"] = button.label
        if hasattr(page, "selected_panel_false"):
            page.selected_panel_false = ""
        for name in ("download_single_file", "download_single_file_simple", "download_all_files"):
            original = getattr(page, name, None)
            if original:
                setattr(page, name, localized_download(original))
