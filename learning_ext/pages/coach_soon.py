"""生成「动手学」开发中占位页的 HTML（单独放，避免 coach.py 头部太长）。"""

# 四个能力 + 一条流程 + 一些还在琢磨的点。
# 注意：这是给用户看的说明，不承诺上线时间，也不要写得像营销页。

_ICON_SANDBOX = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M7 9l2 2-2 2"/><path d="M13 13h4"/></svg>"""

_ICON_EYE = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/></svg>"""

_ICON_ALERT = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l9 16H3L12 3z"/><path d="M12 9v4"/><circle cx="12" cy="16" r=".9" fill="currentColor" stroke="none"/></svg>"""

_ICON_REPORT = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 12h5M10 16h5"/></svg>"""

_ICON_RESET = """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v5h5"/></svg>"""


def coming_soon_html() -> str:
    cards = [
        (
            _ICON_SANDBOX,
            "一台随便折腾的电脑",
            "开一个隔离的沙箱：装软件、改系统设置、写文件、跑命令都行。"
            "弄坏了点一下就复原，你自己电脑上的东西一样都不会动。",
        ),
        (
            _ICON_EYE,
            "它看得见你每一步",
            "不靠录屏。它读的是窗口和控件——你点了哪个按钮、填了什么、"
            "停在哪个界面，所以能跟上你，而不是事后猜。",
        ),
        (
            _ICON_ALERT,
            "走错了当场叫停",
            "第 3 步方向就不对时，它当场说「先别点确定，这里路径写错了」。"
            "等你全部做完再告诉你错在哪，那时候改的成本已经很高了。",
        ),
        (
            _ICON_REPORT,
            "做完给你一份复盘",
            "哪些步骤是你自己想出来的，哪些是照着提示抄的，"
            "下次遇到同类任务先看哪里。错的地方会变成复习卡，过几天再考你一次。",
        ),
    ]

    card_html = "".join(
        f'<article class="soon-card">'
        f'<span class="soon-ico">{ico}</span>'
        f'<h3>{title}</h3>'
        f"<p>{body}</p>"
        f"</article>"
        for ico, title, body in cards
    )

    steps = [
        ("01", "开沙箱", "按这一节要练的东西，起一台干净的机器"),
        ("02", "你动手", "它只说话不动手，除非你让它代劳"),
        ("03", "它盯着", "读窗口、看控件、跟你的操作对进度"),
        ("04", "当场提醒", "偏了就立刻说，不让错误滚雪球"),
        ("05", "收一份复盘", "哪里卡住、哪里该记住，写清楚"),
    ]
    step_html = "".join(
        f'<li><b>{n}</b><span><strong>{t}</strong><em>{d}</em></span></li>'
        for n, t, d in steps
    )

    ideas = [
        "同时开两台：一台给你练，一台演示标准做法，随时对照。",
        "故意埋一个坑——比如藏着一条已经存在的旧配置，练你会不会先检查。",
        "操作类错题回到间隔复习，和概念卡片混着考。",
        "练完一键生成图文步骤，能直接发给同事照着做。",
        "支持「你就看着别说话」模式，全程只在最后给结论。",
    ]
    idea_html = "".join(f"<li>{x}</li>" for x in ideas)

    return f"""<main id="le-soon">
  <header class="soon-head">
    <span class="soon-badge"><i></i>开发中 · 敬请期待</span>
    <h1>动手学</h1>
    <p class="soon-lead">让 AI 坐在你旁边，看着你操作电脑。<br/>走错了当场叫停，做完给你一份复盘。</p>
  </header>

  <section class="soon-grid" aria-label="这个功能会做什么">
    {card_html}
  </section>

  <section class="soon-flow" aria-label="将来的使用流程">
    <div class="soon-sec-head">
      <h2>将来是这样运转的</h2>
      <span>看提示、自己动手、它盯着你</span>
    </div>
    <ol class="soon-steps">{step_html}</ol>
  </section>

  <section class="soon-ideas" aria-label="还在设计中的想法">
    <div class="soon-sec-head">
      <h2>我们还在琢磨</h2>
      <span>下面这些没定，想听你的意见</span>
    </div>
    <ul class="soon-idea-list">{idea_html}</ul>
  </section>

  <section class="soon-cta" aria-label="反馈">
    <div class="soon-cta-text">
      <h3>想让它先支持什么场景？</h3>
      <p>你最想拿它练什么——Excel 函数、命令行、还是某个行业软件？
         把场景告诉我们，比我们猜要准得多。</p>
    </div>
    <div class="soon-cta-action">
      <button type="button" class="soon-btn" data-soon-copy>复制反馈模板</button>
      <span class="soon-tip" data-soon-tip>复制后，在应用内联系客服发给我们即可</span>
    </div>
  </section>

  <footer class="soon-foot">
    <span>{_ICON_RESET}</span>
    想提前看看它在旧版本里的样子？功能开关随时可以打开，只是现在还不稳定，先不拿出来耽误你时间。
  </footer>
</main>"""
