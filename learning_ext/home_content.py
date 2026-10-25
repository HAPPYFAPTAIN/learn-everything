from pathlib import Path


_ART_ROOT = Path(__file__).parent / "assets" / "illustrations"
_ART_FILES = {
    "journey": "learning-journey-v1.png",
    "python": "python-tools-v1.png",
    "ai": "ai-network-v1.png",
    "writing": "writing-v1.png",
}


def illustration(kind, *, eager=False):
    path = (_ART_ROOT / _ART_FILES[kind]).as_posix()
    loading = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    return (
        f'<img class="le-illustration" src="/file={path}" alt="" '
        f'width="1536" height="1024" {loading} decoding="async" draggable="false">'
    )


HERO = f"""<section class="le-discovery-hero">
<div class="le-hero-copy"><h1>让好奇心，<br>长成你的<span>新本领。</span></h1>
<div class="le-hero-actions"><button type="button" data-le-home-action="explore">发现我的学习方向 <span>↗</span></button><button type="button" data-le-home-action="sample">先试一小节 <span>→</span></button></div>
</div>
<div class="le-hero-art le-generated-hero" aria-hidden="true">{illustration("journey", eager=True)}</div></section>"""

DIRECTIONS_HEADING = """<div class="le-discovery-heading"><div><h2>选择一个学习方向</h2></div></div>"""

def direction_art(kind):
    return f'<div class="le-direction-art le-art-{kind}" aria-hidden="true">{illustration(kind)}</div>'
