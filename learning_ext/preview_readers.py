from pathlib import Path

from llama_index.core.readers.base import BaseReader

from learning_ext.document_preview import WORD, prepare_file


class OfficePreviewReader(BaseReader):
    def load_data(self, file, extra_info=None, **kwargs):
        from kotaemon.base import Document
        from pypdf import PdfReader
        path = Path(file)
        document = prepare_file(path, path.name)
        pages = PdfReader(document["path"]).pages
        return [Document(text=page.extract_text() or "此页为图片内容，请在原件预览中阅读。",
                         metadata={**(extra_info or {}), "file_name": path.name, "page_label": number, "type": "text"})
                for number, page in enumerate(pages, 1)]


class PicturePreviewReader(BaseReader):
    def load_data(self, file, extra_info=None, **kwargs):
        from kotaemon.base import Document
        from PIL import Image
        path = Path(file)
        with Image.open(path) as image:
            image.verify()
        return [Document(text=f"图片资料：{path.name}。原件可在资料库中预览；此文件尚未进行文字识别，不能根据文件名推断图片内容。",
                         metadata={**(extra_info or {}), "file_name": path.name, "type": "text", "preview_only": True})]


def configure_preview_readers():
    from kotaemon.indices.ingests.files import KH_DEFAULT_FILE_EXTRACTORS
    for suffix in WORD:
        KH_DEFAULT_FILE_EXTRACTORS[suffix] = OfficePreviewReader()
    for suffix in (".webp", ".bmp", ".gif"):
        KH_DEFAULT_FILE_EXTRACTORS[suffix] = PicturePreviewReader()
