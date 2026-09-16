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


# ══════════════════════════════════════════════════════════════════════
# 以下两条对应线上真实事故，都是「不报错、不 500，只是体验坏掉」的类型，
# 只能靠测试盯住。
# ══════════════════════════════════════════════════════════════════════

CSS = Path(__file__).resolve().parents[2] / "src" / "web" / "static" / "style.css"


def _css_block(selector: str) -> str:
    """取出某个顶层选择器的声明块（不做完整 CSS 解析，够用即可）。"""
    src = CSS.read_text(encoding="utf-8")
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", src)
    assert m, f"style.css 里找不到 {selector} 规则"
    return m.group(1)


def test_loading_indicator_is_hidden_until_on_class():
    """加载提示必须「默认隐藏、靠 .on 显示」。

    事故背景：`#navLoading` 由 JS 创建后长期复用，`hideLoading()` 只做
    「移除 .on」。如果 CSS 里没有 `.on` 规则、基态又是可见的，那么移除类名
    不会有任何视觉变化 —— 遮罩从第一次跳转起就永久盖在页面上，整站看起来
    "蒙了一层且永不消失"（线上真实发生过，且此前所有测试都通过了，
    因为它们只断言类名、不看计算样式）。
    """
    base = _css_block("#navLoading")
    assert re.search(r"visibility\s*:\s*hidden", base), \
        "#navLoading 基态必须 visibility:hidden，否则它一旦创建就永久可见"
    assert re.search(r"opacity\s*:\s*0\b", base), \
        "#navLoading 基态必须 opacity:0"
    assert re.search(r"pointer-events\s*:\s*none", base), \
        "加载提示绝不能拦截用户点击"

    on = _css_block("#navLoading.on")
    assert re.search(r"visibility\s*:\s*visible", on), \
        "#navLoading.on 必须把 visibility 打开（否则加载中看不到提示）"
    assert re.search(r"opacity\s*:\s*1\b", on), \
        "#navLoading.on 必须把 opacity 拉到 1"

    # 基态不能是全屏不透明遮挡：那会把"加载慢"放大成"网站挂了"
    assert "bottom: 0" not in base, "#navLoading 不应铺满视口（会盖住正文）"


def test_nav_targets_do_not_redirect():
    """每个导航项都必须能直连拿到 HTML，不允许依赖 3xx 跳转。

    事故背景：`/screening` 曾被注册成 `/screening/`，访问 `/screening` 会
    返回 `307 Location: http://…/screening/`。应用在平台 https 网关后面，
    redirect 的绝对 URL 是明文 http，页面在 https iframe 内会被浏览器按
    「混合内容」拦掉 —— 用户看到的就是"点漏斗进不去/没反应"。
    浏览器跟随重定向的整页刷新能掩盖这个问题，fetch 局部加载不能。
    """
    html = BASE.read_text(encoding="utf-8")
    nav_hrefs = re.findall(r'<a href="(/[^"]*)"[^>]*aria-label="[^"]*"', html)
    assert nav_hrefs, "没能从 base.html 提取到导航项"

    with TestClient(app) as client:
        for path in nav_hrefs:
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 200, (
                f"导航项 {path} 返回 {r.status_code}"
                + (f"，Location={r.headers.get('location')}" if r.is_redirect else "")
            )
            assert "text/html" in r.headers.get("content-type", ""), path
            assert 'id="page-root"' in r.text, path


def test_stylesheet_url_is_content_versioned():
    """样式表 URL 必须带内容指纹。

    事故背景：`/static/*` 被应用设成 `max-age=14400`，托管平台的边缘节点照此
    缓存；动态 HTML 却是 `no-store`。于是部署后会出现「新页面 + 旧 CSS」——
    样式改了却在长达 4 小时内不生效，而且因为 HTML 变了，很容易被误判成
    "改动没起作用"。带上内容指纹后 URL 随内容变化，旧缓存自然被绕开。
    """
    html = BASE.read_text(encoding="utf-8")
    m = re.search(r'<link rel="stylesheet" href="([^"]+)"', html)
    assert m, "base.html 里找不到样式表 link"
    assert "?v=" in m.group(1), f"样式表 URL 未做版本化：{m.group(1)}"

    from src.web.deps import static_version
    v1 = static_version()
    assert v1 and v1 != "dev", "取不到 style.css 的内容指纹"

    # 渲染出的页面必须带上真实指纹，而不是模板占位符
    with TestClient(app) as client:
        page = client.get("/").text
    assert f'/static/style.css?v={v1}' in page, "渲染结果里没有带上内容指纹"
    assert "{{" not in page.split("style.css")[1][:20], "模板表达式未被渲染"
