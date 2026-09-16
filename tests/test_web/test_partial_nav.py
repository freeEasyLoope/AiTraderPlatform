"""结构回归：异步站内导航（局部加载）依赖的两个「交换边界」。

为什么值得单独用测试守住：
  `#page-root` / `#page-scripts` 一旦缺失或被改名，**不会报错、不会 500**，
  只会让每次点击悄悄退化成整页刷新 —— 用户看到的就是"点了半天没反应"。
  这正是本次要修的体验问题，所以必须有测试盯着。

另外守住一条易碎契约：页面脚本里的**顶层 `let`/`const`**。
  它们进入全局词法环境，同一文档二次注入会抛
  "Identifier 'x' has already been declared"，导致复访该页时脚本整体不执行。
  前端用 `deLexicalize()` 把**行首**的 let/const 降级为 var 来规避；
  本测试冻结"行首 let/const 清单"，新增时必须先确认降级为 var 不会改变语义。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.main import app

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "web" / "templates"
BASE = TEMPLATES / "base.html"

# 行首（零缩进）= 页面脚本的顶层声明。降级为 var 后语义等价（已逐一核对：
# 都是普通常量表 / 布尔开关，没有被同名的块级声明遮蔽）。
EXPECTED_TOPLEVEL_LEXICAL = {
    ("control.html", "PARAM_NAMES"),
    ("control.html", "PARAM_HINTS"),
    ("control.html", "allOpen"),
    ("reports.html", "allReportsOpen"),
}


def test_base_has_swap_boundaries():
    html = BASE.read_text(encoding="utf-8")
    assert html.count('id="page-root"') == 1
    assert html.count('id="page-scripts"') == 1
    # .container 必须在 #page-root 之内：否则局部替换会连容器一起换掉/丢掉
    m = re.search(r'<div id="page-root">(.*?)</div>\s*<!--', html, re.S)
    assert m, "#page-root 结构异常"
    assert '<div class="container">' in m.group(1)
    # 页面脚本边界必须独立于内容边界
    assert 'id="page-scripts"' in html.split('id="page-root"')[1]


def test_base_has_async_nav_engine():
    html = BASE.read_text(encoding="utf-8")
    for key in ("asyncNav", "deLexicalize", "history.pushState", "AbortController", "runScripts"):
        assert key in html, f"异步导航引擎缺少 {key}"
    # 旧的「仅遮罩、仍整页跳转」实现不应残留
    assert "navFeedback" not in html


@pytest.mark.parametrize("tpl", sorted(p.name for p in TEMPLATES.glob("*.html") if p.name != "base.html"))
def test_page_extends_base(tpl):
    """所有页面必须继承 base.html，才能拿到交换边界与导航外壳。"""
    text = (TEMPLATES / tpl).read_text(encoding="utf-8")
    assert '{% extends "base.html" %}' in text, f"{tpl} 未继承 base.html"


def test_rendered_pages_have_boundaries():
    """真实渲染校验：覆盖脚本在 scripts 块（/）与脚本在 content 块（/screening）两种形态。"""
    client = TestClient(app)
    for path in ("/", "/screening"):
        r = client.get(path)
        assert r.status_code == 200, path
        h = r.text
        assert h.count('id="page-root"') == 1, path
        assert h.count('id="page-scripts"') == 1, path
        assert '<div class="container">' in h, path


def test_toplevel_lexical_declarations_are_frozen():
    """冻结行首 let/const 清单：确保 deLexicalize 的降级范围始终是可解释的。"""
    found = set()
    for p in sorted(TEMPLATES.glob("*.html")):
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^(let|const)\s+([A-Za-z_$][\w$]*)", line)
            if m:
                found.add((p.name, m.group(2)))
    assert found == EXPECTED_TOPLEVEL_LEXICAL, (
        "行首 let/const 清单已变化，请先确认降级为 var 不改变语义，再更新本测试。\n"
        f"  新增: {sorted(found - EXPECTED_TOPLEVEL_LEXICAL)}\n"
        f"  消失: {sorted(EXPECTED_TOPLEVEL_LEXICAL - found)}"
    )
