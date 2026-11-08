"""Capture Chrome Web Store art from the real extension, with no school session.

Developer only: requires Playwright with Chromium installed.
"""
from base64 import b64encode
from pathlib import Path
import re
import tempfile

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
OUT = ROOT / "dist" / "chrome-web-store"


def data_uri(png):
    return "data:image/png;base64," + b64encode(png).decode("ascii")


def screenshot(panel, art, icon, filename, title, details, tags):
    view = data_uri(panel.screenshot(animations="disabled"))
    chips = "".join(f"<span>{tag}</span>" for tag in tags)
    art.set_viewport_size({"width": 1280, "height": 800})
    art.set_content(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
      * {{box-sizing:border-box}} body {{margin:0;color:#173c30;font-family:'Microsoft YaHei','PingFang SC',sans-serif;
      background:radial-gradient(ellipse at 8% 5%,#eff5da,transparent 65%),#e0eee5;}}
      main {{height:800px;display:grid;grid-template-columns:1fr 520px;gap:54px;padding:40px 64px 40px 74px;align-items:center;}}
      .brand {{display:flex;align-items:center;gap:14px;font-size:22px;font-weight:700;}}
      .brand img {{width:47px;height:47px;}} h1 {{font-size:54px;line-height:1.2;letter-spacing:-1px;margin:38px 0 25px;}}
      p {{font-size:23px;line-height:1.75;margin:0 0 32px;color:#36594e;max-width:485px;}}
      .tags {{display:flex;gap:10px;flex-wrap:wrap;}} .tags span {{background:#f7faf5;border:1px solid #cadbcf;
      color:#275142;border-radius:999px;padding:9px 14px;font-size:17px;}} small {{display:block;margin-top:36px;color:#48645a;font-size:15px;}}
      .panel {{display:block;width:520px;height:720px;outline:1px solid #c9dad0;border-radius:17px;box-shadow:0 18px 42px #173c3026;}}
    </style><main><section><div class="brand"><img src="{icon}" alt="">网球预约助手</div><h1>{title}</h1>
    <p>{details}</p><div class="tags">{chips}</div><small>适用于上海交大体育场馆预约网站 · 非官方</small></section>
    <img class="panel" src="{view}" alt="实际扩展侧边栏"></main></html>""")
    art.screenshot(path=OUT / filename, animations="disabled")


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    icon = data_uri((EXT / "icons" / "icon128.png").read_bytes())
    with tempfile.TemporaryDirectory(prefix="sjtu-store-assets-") as profile, sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
            viewport={"width": 650, "height": 900}, device_scale_factor=1,
        )
        try:
            context.route(re.compile(r"^https?://"), lambda route: route.abort())
            worker = next(iter(context.service_workers), None) or context.wait_for_event("serviceworker")
            panel = context.new_page()
            panel.goto(worker.url.rsplit("/", 1)[0] + "/sidepanel.html")
            panel.wait_for_function("() => document.querySelector('[name=dateText]').value.length > 0")
            art = context.new_page()
            screenshot(panel, art, icon, "01-monitor.png", "发现空场，<br>及时收到提醒。",
                       "按场馆、日期和时段监控。只想收提醒时，可以关闭自动下单。",
                       ["双场馆", "自选时段", "本机通知"])
            panel.locator("#mode-rush").click()
            panel.locator("#rush-form").wait_for()
            screenshot(panel, art, icon, "02-scheduled-booking.png", "设好优先级，<br>到点尝试预约。",
                       "选好场地和备选时段，到设定时间后在学校网页尝试自动提交。",
                       ["按时开始", "备选时段", "可随时停止"])

            art.set_viewport_size({"width": 128, "height": 128})
            art.set_content(f'<body style="margin:16px"><img src="{icon}" width="96" height="96" alt=""></body>')
            art.screenshot(path=OUT / "icon-128.png", omit_background=True)

            art.set_viewport_size({"width": 440, "height": 280})
            art.set_content(f"""<!doctype html><meta charset="utf-8"><style>
              body {{margin:0;background:linear-gradient(140deg,#2a6b55,#163e34);display:grid;place-items:center;height:280px;}}
              svg {{position:absolute;inset:0;}} img {{position:relative;box-shadow:0 10px 32px #102e2766;border-radius:30px;}}
            </style><svg width="440" height="280" viewBox="0 0 440 280" aria-hidden="true">
              <path d="M43 33h354v214H43z M43 66h354 M43 214h354 M132 66v148 M308 66v148 M132 140h176"
              fill="none" stroke="#e0f0da" stroke-opacity=".38" stroke-width="2"/>
            </svg><img src="{icon}" width="128" height="128" alt="">""")
            art.screenshot(path=OUT / "promo-440x280.png")
        finally:
            context.close()
    print(OUT)


if __name__ == "__main__":
    run()
