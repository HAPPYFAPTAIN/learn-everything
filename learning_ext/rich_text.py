from __future__ import annotations

from html import escape
import re

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound


_COMMAND = re.compile(
    r"^(?:mkdir|cd|pwd|dir|ls|python(?:3|\.exe)?|py|pip3?|uv|conda|"
    r"npm|npx|pnpm|yarn|node|git|docker|winget|choco|code|curl|"
    r"Get-[A-Za-z]+|Set-[A-Za-z]+|New-[A-Za-z]+|Test-[A-Za-z]+|"
    r"Write-[A-Za-z]+|Import-[A-Za-z]+|Install-[A-Za-z]+|"
    r"\.\\[^\s]+\.(?:ps1|exe))(?=\s|$)", re.I,
)
_LABELS = {"powershell": "PowerShell", "ps1": "PowerShell", "pwsh": "PowerShell",
           "python": "Python", "py": "Python", "bash": "Bash", "sh": "Shell",
           "javascript": "JavaScript", "js": "JavaScript", "typescript": "TypeScript",
           "ts": "TypeScript", "json": "JSON", "html": "HTML", "css": "CSS",
           "sql": "SQL", "text": "文本", "plaintext": "文本"}
_ALIASES = {"ps1": "powershell", "pwsh": "powershell"}
_COPY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>'


def _code_block(tokens, index, options, env):
    token = tokens[index]
    language = token.info.strip().split()[0].lower() if token.info.strip() else ""
    code = token.content
    rendered = escape(code)
    if language:
        try:
            lexer = get_lexer_by_name(_ALIASES.get(language, language), stripnl=False, ensurenl=False)
            rendered = highlight(code, lexer, HtmlFormatter(nowrap=True))
        except ClassNotFound:
            pass
    label = _LABELS.get(language, language or "代码")
    return (
        '<section class="le-code-block" aria-label="代码片段">'
        f'<div class="le-code-toolbar"><span class="le-code-language">{escape(label)}</span>'
        f'<button type="button" class="le-code-copy" aria-label="复制代码">{_COPY_ICON}'
        '<span aria-live="polite">复制</span></button></div>'
        f'<pre tabindex="0" aria-label="{escape(label)}代码"><code>{rendered}</code></pre></section>\n'
    )


def _parser():
    parser = MarkdownIt("commonmark", {"html": False, "breaks": True}).disable("image")
    parser.renderer.rules["fence"] = _code_block
    parser.renderer.rules["code_block"] = _code_block
    return parser


def _command_line(line):
    if not _COMMAND.match(line):
        return False
    unquoted = re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', '', line.split(" #", 1)[0])
    return not re.search(r"[\u4e00-\u9fff]", unquoted)


def _legacy_commands(text, parser):
    lines = text.splitlines(keepends=True)
    eligible = set()
    for token in parser.parse(text):
        if token.type == "paragraph_open" and token.level == 0 and token.map:
            eligible.update(range(*token.map))
    output = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        if index not in eligible or not _command_line(line):
            output.append(lines[index])
            index += 1
            continue
        commands = []
        while index < len(lines) and index in eligible and (
            _command_line(lines[index]) or (commands and commands[-1].rstrip().endswith("`"))
        ):
            commands.append(lines[index].rstrip("\r\n"))
            index += 1
        # Fences avoid changing existing code and preserve literal command arguments.
        fence = "`" * max(3, 1 + max((len(m[0]) for command in commands for m in re.finditer(r"`+", command)), default=0))
        output.append("\n" + fence + "powershell\n" + "\n".join(commands) + "\n" + fence + "\n\n")
    return "".join(output)


def render_rich_text(value, *, legacy_commands=False):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    parser = _parser()
    if legacy_commands:
        text = _legacy_commands(text, parser)
    return '<div class="le-rich-text">' + parser.render(text) + '</div>'
