def polish_library_ui(app):
    labels = {
        "File Collection": "文件资料", "GraphRAG Collection": "图谱资料 · 可选扩展",
        "LightRAG Collection": "关联资料 · 可选扩展", "Upload Files": "上传文件",
        "Use Web Links": "导入网页", "Input web URLs": "网页地址",
        "Advanced indexing options": "索引选项", "Force reindex file": "重新解析已上传的文件",
        "Upload result": "处理结果", "Upload info": "处理进度", "Files": "文件",
        "Groups": "分组", "Filter by name:": "搜索文件名称", "Advance options": "更多操作",
        "Chunk type": "内容类型", "Group name": "分组名称", "File": "文件",
    }
    values = {
        "Upload and Index": "上传并建立索引", "## Upload Progress": "## 文件处理进度",
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
        if getattr(block, "info", None) == "(1) Case-insensitive. (2) Search with empty string to show all files.":
            block.info = "输入名称筛选，留空显示全部文件。"
        value = getattr(block, "value", None)
        if isinstance(value, str):
            if value in values:
                block.value = values[value]
            elif value.startswith("- Supported file types:"):
                block.value = value.replace("Supported file types:", "支持格式：").replace("Maximum file size:", "单个文件上限：")

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
            page.selected_panel_false = "选择上方文件，查看正文片段与来源。"
        for name in ("download_single_file", "download_single_file_simple", "download_all_files"):
            original = getattr(page, name, None)
            if original:
                setattr(page, name, localized_download(original))
