import json
import re

from learning_ext.route_view import next_route_node, render_route, route_action_label


def test_thirty_course_route_only_expands_next_stage_and_keeps_every_course():
    nodes = []
    for stage_number, stage in enumerate(("base", "strengthen", "sprint"), 1):
        for course_number in range(1, 11):
            code = f"{stage_number}.{course_number}"
            nodes.append({
                "code": code,
                "title": f"Course {code}",
                "stage": stage,
                "status": "pending",
                "est_hours": course_number % 3 + 1,
                "description": f"说明 {code}",
                "prerequisites": [],
            })
    nodes[0]["status"] = "mastered"
    nodes[10]["status"] = "learning"

    content = render_route({"nodes": nodes})
    stages = re.findall(r'<details class="le-route-stage([^"]*)"([^>]*)>', content)

    assert len(stages) == 3
    assert ["open" in attrs for _, attrs in stages] == [False, True, False]
    assert ["is-current" in classes for classes, _ in stages] == [False, True, False]
    assert content.count('class="le-route-course"') == 30
    assert content.index('aria-label="当前阶段与下一节"') < content.index('class="le-route-metrics"')
    focus = content.split('<div class="le-route-metrics">', 1)[0]
    assert "下一节 · 学习中" in focus
    assert "[2.1] Course 2.1" in focus
    for node in nodes:
        assert f'[{node["code"]}]' in content
        assert node["description"] in content
        assert f'>{node["est_hours"]} 小时</span>' in content
    assert "已掌握" in content and "学习中" in content and "待学习" in content


def test_next_course_prioritizes_learning_then_weak_then_pending():
    nodes = [
        {"code": "1.1", "status": "pending"},
        {"code": "3.1", "status": "weak"},
        {"code": "2.1", "status": "learning"},
    ]
    roadmap = {"nodes": nodes}

    assert next_route_node(roadmap)["code"] == "2.1"
    nodes[2]["status"] = "mastered"
    assert next_route_node(roadmap)["code"] == "3.1"
    nodes[1]["status"] = "mastered"
    assert next_route_node(roadmap)["code"] == "1.1"


def test_completed_and_empty_routes_have_explicit_focus_states():
    completed = render_route({"nodes": [
        {"code": "1.1", "title": "Done", "stage": "base", "status": "mastered"},
        {"code": "2.1", "title": "Also done", "stage": "strengthen", "status": "mastered"},
    ]})

    assert "全部完成" in completed
    assert "下一节 ·" not in completed
    assert not re.search(r'class="le-route-stage[^"]*" open', completed)
    assert route_action_label({"nodes": [{"status": "mastered"}]}) == "打开课程，回顾已学内容 →"
    empty = render_route({})
    assert "暂无学习路线" in empty
    assert "从学习首页创建一个目标" in empty
    assert 'role="status"' in empty


def test_existing_open_course_action_uses_the_same_next_course():
    from learning_ext.pages.path_generator import PathGeneratorPage

    raw = json.dumps({"nodes": [{
        "code": "2.1",
        "title": "继续这一节",
        "stage": "strengthen",
        "status": "learning",
    }]}, ensure_ascii=False)

    open_course = PathGeneratorPage._route_actions(raw, 9)[2]

    assert open_course["visible"] is True
    assert open_course["value"] == "继续学习：[2.1] 继续这一节 →"


def test_route_styles_are_loaded_exactly_once():
    import inspect

    from learning_ext.presentation import presentation_css

    css = presentation_css()
    source = inspect.getsource(presentation_css)

    assert source.count('(ASSETS / "route.css")') == 1
    assert "#le-route-output .le-route-focus{" in css
    assert "#le-route-output .le-route-stage>summary" in css
    assert "summary:focus-visible" in css
