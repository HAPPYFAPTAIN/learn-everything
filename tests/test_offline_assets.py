import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "learning_ext" / "assets"


def test_frontend_entrypoints_are_local_and_vendor_files_exist():
    source = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")
    custom = (ROOT / "custom_app.py").read_text(encoding="utf-8")
    make = source.split("def make(self):", 1)[1].split("with gr.Blocks", 1)[0]

    assert "cdn.skypack.dev" not in make
    assert "cdnjs.cloudflare.com" not in make
    assert "cdn.jsdelivr.net" not in make
    assert "vendor/iframe-resizer/iframeResizer.contentWindow.min.js" in custom
    assert (ASSETS / "vendor" / "iframe-resizer" / "iframeResizer.contentWindow.min.js").is_file()
    paths = set(re.findall(r"/vendor/([a-zA-Z0-9_./-]+)", make))
    expected = {
        "pdfjs/pdfjs-viewer-element.js",
        "d3/d3.min.js",
        "markmap/autoloader.js",
        "markmap/lib.js",
        "markmap/view.js",
        "markmap/toolbar.js",
        "markmap/toolbar.css",
        "tribute/tribute.min.js",
        "tribute/tribute.css",
        "minisearch/index.js",
    }
    assert expected <= paths
    for relative in paths:
        assert (ASSETS / "vendor" / relative).is_file(), relative
        assert (ASSETS / "vendor" / relative).stat().st_size > 0, relative


def test_pdf_component_has_all_dynamic_imports_and_no_forced_locale_download():
    source = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")
    component = (ASSETS / "vendor" / "pdfjs" / "pdfjs-viewer-element.js").read_text(encoding="utf-8")

    assert 'self._pdf_view_js.replace(\'locale="en"\', "")' in source
    for relative in re.findall(r'import\("(\./[^"]+)"\)', component):
        assert (ASSETS / "vendor" / "pdfjs" / relative[2:]).is_file(), relative
    assert 'new URL("./pdf.worker.min.mjs",import.meta.url)' in component
    assert 'if(this.getAttribute("src"))await this.buildViewerApp()' in component
    assert 'if(!t&&r)await this.buildViewerApp()' in component
    assert (ASSETS / "vendor" / "pdfjs" / "pdf.worker.min.mjs").is_file()


def test_markmap_provider_uses_pinned_local_versions():
    source = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")

    for key in (
        "d3@7.8.5",
        "markmap-lib@0.16.1",
        "markmap-view@0.16.0",
        "markmap-toolbar@0.16.0",
        "markmap-toolbar@0.16.0/dist/style.css",
    ):
        assert f"'{key}'" in source
    assert "provider: (path) =>" in source


def test_vendor_licenses_are_present():
    for directory in ("pdfjs", "d3", "markmap", "tribute", "minisearch", "iframe-resizer"):
        licenses = list((ASSETS / "vendor" / directory).glob("*LICENSE*"))
        assert licenses, directory
        assert all(path.stat().st_size > 0 for path in licenses)


def test_theme_fonts_are_local_and_preserve_original_families():
    source = (ROOT / "learning_ext" / "app.py").read_text(encoding="utf-8")
    presentation = (ROOT / "learning_ext" / "presentation.py").read_text(encoding="utf-8")

    assert "self._theme = type(self._theme)(" in source
    assert 'font=["Quicksand", "ui-sans-serif", "sans-serif"]' in source
    assert 'font_mono=["IBM Plex Mono", "ui-monospace", "monospace"]' in source
    assert 'ASSETS / "vendor/fonts/fonts.css"' in presentation
    for name in (
        "quicksand-regular.ttf",
        "quicksand-semibold.ttf",
        "ibm-plex-mono-regular.ttf",
        "ibm-plex-mono-semibold.ttf",
        "quicksand-OFL.txt",
        "ibm-plex-mono-OFL.txt",
    ):
        assert (ASSETS / "vendor" / "fonts" / name).is_file(), name
