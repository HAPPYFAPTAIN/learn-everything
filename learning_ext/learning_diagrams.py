import json
from html import escape
from textwrap import wrap
from uuid import uuid4


def render_learning_diagram(source):
    data = json.loads(source)
    nodes = data['nodes']
    edges = data.get('edges', [])
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 10 or len(edges) > 18:
        raise ValueError('图中需要 2–10 个节点，最多 18 条连线')
    labels = {}
    for node in nodes:
        key, label = str(node['id']), str(node['label'])
        if key in labels or not label.strip() or len(label) > 60:
            raise ValueError('节点编号必须唯一，名称不超过 60 字')
        labels[key] = label
    links = [(str(edge[0]), str(edge[1])) for edge in edges if isinstance(edge, list) and len(edge) == 2]
    if len(links) != len(edges) or any(a not in labels or b not in labels for a, b in links):
        raise ValueError('连线需要引用已存在的节点')
    levels = dict.fromkeys(labels, 0)
    for iteration in range(len(nodes)):
        changed = False
        for a, b in links:
            if levels[b] <= levels[a]:
                levels[b] = levels[a] + 1
                changed = True
        if not changed:
            break
    else:
        raise ValueError('请使用无环结构；循环请拆成顺序步骤')
    if max(levels.values()) > 5:
        raise ValueError('图层过多，请拆成两张图')
    rows = [[key for key in labels if levels[key] == level] for level in range(max(levels.values()) + 1)]
    width = max(600, max(map(len, rows)) * 180)
    height = len(rows) * 110 + 20
    positions = {}
    for level, row in enumerate(rows):
        for index, key in enumerate(row):
            positions[key] = ((index + .5) * width / len(row), 20 + level * 110)
    marker = 'le-arrow-' + uuid4().hex
    svg = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(str(data.get("title", "知识结构图")), quote=True)}">', f'<defs><marker id="{marker}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" class="le-diagram-arrow"/></marker></defs>']
    for a, b in links:
        x1, y1 = positions[a]; x2, y2 = positions[b]
        svg.append(f'<path class="le-diagram-link" d="M{x1} {y1+64} C{x1} {y1+88} {x2} {y2-24} {x2} {y2}" marker-end="url(#{marker})"/>')
    for key, label in labels.items():
        x, y = positions[key]
        lines = wrap(label, width=12, break_long_words=True)[:5]
        svg.append(f'<g class="le-diagram-node le-diagram-tone-{levels[key] % 4}"><rect x="{x-78}" y="{y}" width="156" height="64" rx="12"/>')
        for index, line in enumerate(lines):
            svg.append(f'<text x="{x}" y="{y+34+(index-(len(lines)-1)/2)*12}" text-anchor="middle">{escape(line)}</text>')
        svg.append('</g>')
    svg.append('</svg>')
    relationships = ''.join(f'<li>{escape(labels[a])} → {escape(labels[b])}</li>' for a, b in links)
    return '<figure class="le-learning-diagram"><figcaption>' + escape(str(data.get('title', '知识结构图'))) + '</figcaption>' + ''.join(svg) + '<details><summary>文字版关系</summary><ul>' + relationships + '</ul></details></figure>'
