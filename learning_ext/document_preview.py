from __future__ import annotations

import base64
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import threading
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINES = ROOT / "vendor" / "preview"
CACHE = ROOT / "ktem_app_data" / "document_previews"
WORD = {".doc", ".docx", ".odt", ".rtf"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SUPPORTED = WORD | IMAGES | {".pdf"}
_CONVERSION_LOCK = threading.Lock()


def engine_paths():
    return ENGINES / "libreoffice/program/soffice.com", ENGINES / "sumatra/sumatrapdf-tool.exe"


def _run(args, timeout=90):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise ValueError("预览组件无法读取这份文件，文件可能已损坏或受到密码保护。")


def source_file(index, file_id, user_id):
    from ktem.db.engine import engine
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    Source = index._resources["Source"]
    with Session(engine) as session:
        query = select(Source).where(Source.id == file_id)
        if index.config.get("private", False):
            query = query.where(Source.user == str(user_id))
        source = session.execute(query).scalar_one_or_none()
        if source is None:
            raise ValueError("没有找到这份资料，或你没有访问权限。")
        root = Path(index._fs_path).resolve()
        path = (root / source.path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("原始文件已不在资料库中，可以继续阅读解析内容。")
        return path, source.name


def prepare_file(path, name):
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        return None
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("这份文件较大，暂不生成原件预览，可继续阅读解析内容。")
    stat = path.stat()
    identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{suffix}"
    folder = CACHE / hashlib.sha256(identity.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / ("original" + suffix)
    with _CONVERSION_LOCK:
        if not original.exists():
            shutil.copyfile(path, original)
        document = original
        renderer = "图片"
        if suffix in WORD:
            document = folder / "original.pdf"
            renderer = "LibreOffice · SumatraPDF"
            if not document.exists():
                office, _ = engine_paths()
                if not office.is_file():
                    raise ValueError("软件内置的 Word 预览组件缺失，请修复应用安装。")
                profile_root = ROOT / ".tmp"
                profile_root.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="office-", dir=profile_root) as temp:
                    profile = Path(temp) / "profile"
                    (profile / "user").mkdir(parents=True)
                    (profile / "user/registrymodifications.xcu").write_text(
                        '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>', encoding="utf-8")
                    _run([office, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo", "--norestore",
                          "--convert-to", "pdf:writer_pdf_Export", "--outdir", folder, original], timeout=120)
                if not document.exists() or not document.stat().st_size:
                    raise ValueError("Word 原件预览未能生成，可继续阅读解析内容。")
        if suffix == ".pdf" or suffix in WORD:
            from pypdf import PdfReader
            pdf = PdfReader(str(document))
            if pdf.is_encrypted and not pdf.decrypt(""):
                raise ValueError("这份文件有密码保护，请先上传已解锁的副本。")
            count = len(pdf.pages)
            renderer = renderer if suffix in WORD else "SumatraPDF"
            kind = "pdf"
        else:
            from PIL import Image
            with Image.open(original) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("图片分辨率过高，请使用较小的副本预览。")
                count = getattr(image, "n_frames", 1)
            kind = "image"
    return {"path": str(document), "folder": str(folder), "pages": count, "name": name, "kind": kind, "renderer": renderer}


def render_page(document, page_number=1):
    if not document:
        return "", 1, ""
    page_number = max(1, min(int(page_number or 1), document["pages"]))
    path = Path(document["path"]).resolve()
    if not path.is_relative_to(CACHE.resolve()) or not path.is_file():
        raise ValueError("预览已过期，请重新选择资料。")
    output = path.parent / f"page-{page_number}.png"
    with _CONVERSION_LOCK:
        if not output.exists():
            if document["kind"] == "pdf":
                _, sumatra = engine_paths()
                if not sumatra.is_file():
                    raise ValueError("软件内置的 PDF 预览组件缺失，请修复应用安装。")
                _run([sumatra, "draw", "-q", "-F", "png", "-r", "120", "-w", "1600", "-h", "2200", "-m", "268435456", "-o", output, path, str(page_number)])
            else:
                from PIL import Image, ImageOps
                with Image.open(path) as image:
                    image.seek(page_number - 1)
                    image = ImageOps.exif_transpose(image).convert("RGBA")
                    image.thumbnail((1800, 2200))
                    image.save(output, "PNG")
        if not output.is_file():
            raise ValueError("暂时无法渲染这一页，请重试。")
        encoded = base64.b64encode(output.read_bytes()).decode()
    name = escape(document["name"], quote=True)
    html = f'<div class="le-original-toolbar"><span>{escape(document["renderer"])}</span><button type="button" data-preview-zoom="out" aria-label="缩小">−</button><button type="button" data-preview-zoom="fit">适合宽度</button><button type="button" data-preview-zoom="in" aria-label="放大">＋</button><button type="button" data-preview-fullscreen aria-label="全屏阅读">⛶</button></div><div class="le-original-canvas"><img src="data:image/png;base64,{encoded}" alt="{name} · 第 {page_number} 页" draggable="false"></div>'
    return html, page_number, f"{page_number} / {document['pages']}"


def attach_preview(app, page, index):
    import gradio as gr
    with page.selection_info:
        with gr.Column(visible=False, elem_classes=["le-source-original"]) as panel:
            state = gr.State(None)
            gr.HTML('<div class="le-original-title">原件预览</div>')
            with gr.Row(elem_classes=["le-preview-pagination"]):
                previous = gr.Button("上一页", size="sm", scale=0)
                number = gr.Number(value=1, minimum=1, precision=0, label="页码", show_label=False, min_width=65, scale=0)
                counter = gr.Markdown("")
                following = gr.Button("下一页", size="sm", scale=0)
            view = gr.HTML("")

    def load(file_id, user_id):
        if not file_id:
            yield gr.update(visible=False), None, "", 1, "", gr.update(interactive=False), gr.update(interactive=False)
            return
        yield gr.update(visible=True), None, '<div class="le-preview-loading" role="status">正在准备原件预览…</div>', 1, "", gr.update(interactive=False), gr.update(interactive=False)
        try:
            path, name = source_file(index, file_id, user_id)
            document = prepare_file(path, name)
            if not document:
                yield gr.update(visible=False), None, "", 1, "", gr.update(interactive=False), gr.update(interactive=False)
                return
            html, current, total = render_page(document)
            yield gr.update(visible=True), document, html, current, total, gr.update(interactive=False), gr.update(interactive=document["pages"] > 1)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "原件预览暂时不可用，可以继续阅读下方解析内容。"
            yield gr.update(visible=True), None, f'<p class="le-preview-message">{escape(message)}</p>', 1, "", gr.update(interactive=False), gr.update(interactive=False)

    def navigate(document, current, delta=0):
        try:
            html, number, total = render_page(document, (current or 1) + delta)
            return html, number, total, gr.update(interactive=bool(document and number > 1)), gr.update(interactive=bool(document and number < document["pages"]))
        except Exception as exc:
            raise gr.Error(str(exc) if isinstance(exc, ValueError) else "翻页失败，请重新选择资料。")

    page.selected_file_id.change(load, [page.selected_file_id,app.user_id], [panel,state,view,number,counter,previous,following], show_progress="hidden", trigger_mode="always_last")
    outputs = [view,number,counter,previous,following]
    previous.click(lambda doc, n: navigate(doc, n, -1), [state,number], outputs, show_progress="hidden")
    following.click(lambda doc, n: navigate(doc, n, 1), [state,number], outputs, show_progress="hidden")
    number.submit(navigate, [state,number], outputs, show_progress="hidden")
    with page.upload_button.parent:
        original_button = gr.Button("仅保存原件 · 不调用模型", variant="secondary")
        original_status = gr.Markdown("")

    def add_originals(files, user_id):
        if not files:
            raise gr.Error("先选择要保存的文件。")
        try:
            selected_id, selected_name, count = save_originals(index, files, user_id)
            return f"已保存 {count} 份原件，可直接预览。需要知识检索时，使用“更新已有资料”重新解析。", selected_id, page.selected_panel_true.format(name=selected_name), None
        except ValueError as exc:
            raise gr.Error(str(exc))

    original_button.click(add_originals, [page.files,app.user_id], [original_status,page.selected_file_id,page.selected_panel,page.files], show_progress="hidden").then(
        page.list_file, [app.user_id,page.filter], [page.file_list_state,page.file_list], show_progress="hidden",
    ).then(page.file_selected, [page.selected_file_id], [page.chunks,page.deselect_button,page.delete_button,page.download_single_button,page.chat_button,page.chunk_header,page.chunk_type_filter], show_progress="hidden")


def save_originals(index, files, user_id):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from ktem.db.engine import engine
    from theflow.settings import settings
    upload_root = Path(os.environ.get("GRADIO_TEMP_DIR", str(Path(settings.KH_APP_DATA_DIR) / "gradio_tmp"))).resolve()
    Source = index._resources["Source"]
    destination = Path(index._fs_path).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    selected = []
    with Session(engine) as session:
        for file in files:
            path = Path(file).resolve()
            if not path.is_relative_to(upload_root) or not path.is_file():
                raise ValueError("请通过上传窗口选择文件。")
            if path.suffix.lower() not in SUPPORTED or path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("原件预览支持 100 MB 以内的 Word、PDF 和常见图片。")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            query = select(Source).where(Source.name == path.name)
            if index.config.get("private", False):
                query = query.where(Source.user == str(user_id))
            existing = session.execute(query).scalar_one_or_none()
            if existing:
                if existing.path != digest:
                    raise ValueError(f"已存在同名资料 {path.name}，请为新文件改名后再添加。")
                selected.append((existing.id, existing.name))
                continue
            shutil.copyfile(path, destination / digest)
            source = Source(name=path.name, path=digest, size=path.stat().st_size, user=str(user_id), note={"loader": "原件预览", "preview_only": True})
            session.add(source)
            session.flush()
            selected.append((source.id, source.name))
        session.commit()
    return *selected[0], len(selected)
