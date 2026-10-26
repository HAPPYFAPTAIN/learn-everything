import json
from bs4 import BeautifulSoup
from learning_ext.rich_text import render_lesson


def test_existing_exercise_blanks_survive_without_arbitrary_styles():
    soup = BeautifulSoup(render_lesson('填入 <span class="le-blank" style="width:3.3em"></span>。'), 'html.parser')
    assert soup.select_one('.le-blank')['style'] == 'width:3.3em'
    unsafe = render_lesson('<span class="le-blank" style="width:3.3em" onclick="alert(1)">x</span>')
    assert not BeautifulSoup(unsafe, 'html.parser').select('[onclick]')


def test_lesson_keeps_tables_disclosures_and_safe_marks():
    html = render_lesson('## 本节小结\n\n==重点|先验证== ++记住++\n\n|名称|含义|\n|---|---|\n|A|B|\n\n<details><summary>点击查看答案</summary>\n\n**答案**：A\n\n</details>\n<script>alert(1)</script>')
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('table td').text == 'A'
    assert soup.select_one('details summary').text == '点击查看答案'
    assert soup.select_one('details strong').text == '答案'
    assert soup.select_one('mark').text == '先验证'
    assert not soup.select('script')


def test_diagram_renders_branches_and_accessible_relationships():
    data = {'title':'环境检查','nodes':[{'id':'a','label':'确认目标'},{'id':'b','label':'已经安装'},{'id':'c','label':'需要安装'}], 'edges':[['a','b'],['a','c']]}
    soup = BeautifulSoup(render_lesson('```learning-diagram\n'+json.dumps(data)+'\n```'), 'html.parser')
    assert len(soup.select('svg rect')) == 3
    assert len(soup.select('.le-diagram-link')) == 2
    assert soup.select_one('figcaption').text == '环境检查'
    assert '确认目标 → 已经安装' in soup.select_one('details').text


def test_invalid_diagram_preserves_content_without_breaking_lesson():
    for raw in ['invalid json', '{"nodes":[]}', '{"nodes":[{"id":"a","label":"A"},{"id":"b","label":"B"}],"edges":[["a","b"],["b","a"]]}']:
        soup = BeautifulSoup(render_lesson('正文\n\n```learning-diagram\n'+raw+'\n```\n\n## 本节小结\n仍可阅读'), 'html.parser')
        assert soup.select_one('.le-diagram-fallback')
        assert '仍可阅读' in soup.text


def test_diagram_escapes_untrusted_labels():
    data={'title':'<script>x</script>','nodes':[{'id':'a','label':'<img onerror=x>'},{'id':'b','label':'B'}], 'edges':[['a','b']]}
    soup=BeautifulSoup(render_lesson('```learning-diagram\n'+json.dumps(data)+'\n```'), 'html.parser')
    assert not soup.select('script,img')
