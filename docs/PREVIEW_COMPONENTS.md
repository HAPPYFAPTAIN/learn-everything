# 内置资料预览

运行时仅从应用的 `vendor/preview` 读取预览引擎，不依赖用户安装的 Office、LibreOffice 或 PDF 阅读器，也不启动外部阅读窗口。

- Word（DOC/DOCX/ODT/RTF）：LibreOffice Writer 在独立临时用户配置中转换为 PDF；禁用宏执行。默认转换超时为 120 秒。
- PDF：SumatraPDF 的独立命令行程序 `sumatrapdf-tool.exe` 和 `libmupdf.dll` 按需渲染单页 PNG。前端提供翻页、缩放、适合宽度与全屏。
- 图片（PNG/JPEG/WebP/GIF/BMP/TIFF）：现有 Pillow 依赖渲染；多帧文件可以翻页。浏览器只接收图片，不执行文档脚本。
- 预览缓存位于本机 `ktem_app_data/document_previews`，按原文件版本生成；原件不修改。最多预览 100 MiB 的文件和 4000 万像素的图片。

## 组装

开发机运行 `scripts/bundle_preview_engines.ps1`，将已安装的发行版复制到应用目录。脚本只收集程序、资源和许可证，不复制个人配置。`pack_portable.bat` 会将此目录纳入便携版；缺少组件时停止打包。LibreOffice 的字体、布局和过滤器资源需一起保留，不能只复制 soffice.exe。

预览 UI 较轻，但 LibreOffice 文档排版引擎本身会增加发行包体积。打包目录包含原发行版的许可证与声明。

## 上游与源码

- LibreOffice / The Document Foundation：MPL 2.0 等许可证，以附带 `libreoffice/LICENSE.html`、`license.txt`、`NOTICE` 为准。源码与发行版本：https://www.libreoffice.org/download/download-libreoffice/ ，https://download.documentfoundation.org/libreoffice/src/ 。转换参数：https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html 。
- SumatraPDF / Krzysztof Kowalczyk 及贡献者：GPLv3，包含 MuPDF 等组件；许可证 `sumatra/COPYING`。完整源码及子模块：https://github.com/sumatrapdfreader/sumatrapdf ，对应发行标签：https://github.com/sumatrapdfreader/sumatrapdf/tags 。渲染参数：https://www.sumatrapdfreader.org/docs/Tool-draw 。

发布便携版时保留上述许可证、上游版权声明，并在发布页提供与捆绑二进制版本相对应的完整源码获取地址。
