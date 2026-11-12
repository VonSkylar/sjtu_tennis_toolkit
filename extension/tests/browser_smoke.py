"""Load the real extension in a fresh Chromium profile; all bookings use a fixture.

Run: python -X utf8 extension/tests/browser_smoke.py
No user browser profile, credentials, or real booking submission is used.
"""
from pathlib import Path
import json
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
OUT = ROOT / "build" / "extension-validation"
FIXTURE = (EXT / "tests" / "booking-fixture.html").read_text(encoding="utf-8")
OUT.mkdir(parents=True, exist_ok=True)

def run():
    events, errors, checks = [], [], []
    config = {"outcome": "success", "multiple": False}
    def checked(label, condition):
        if not condition:
            raise AssertionError(label)
        checks.append(label)
        print("PASS", label, flush=True)
    with tempfile.TemporaryDirectory(prefix="sjtu-extension-") as profile, sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
            viewport={"width": 1400, "height": 1100},
        )
        def observe(page):
            page.on("console", lambda msg: events.append(json.loads(msg.text[8:])) if msg.text.startswith("FIXTURE:") else None)
            page.on("pageerror", lambda error: errors.append(error.stack))
        context.on("page", observe)
        context.route("https://sports.sjtu.edu.cn/**", lambda route: route.fulfill(status=200, content_type="text/html", body=FIXTURE.replace("__FIXTURE_CONFIG__", json.dumps(config))))
        workers = context.service_workers
        worker = workers[0] if workers else context.wait_for_event("serviceworker")
        extension_id = worker.url.split("/")[2]
        panel_url = f"chrome-extension://{extension_id}/sidepanel.html"
        panel = context.new_page()
        panel.set_viewport_size({"width": 380, "height": 1100})
        panel.goto(panel_url)
        try:
            panel.wait_for_function("() => document.querySelector('[name=dateText]').value.length > 0", timeout=8000)
        except Exception:
            print("INIT UI", panel.locator("body").inner_text(), "ERRORS", errors, flush=True)
            panel.screenshot(path=str(OUT / "init-error.png"), full_page=True)
            raise
        def send(kind, **extra):
            result = panel.evaluate("m => chrome.runtime.sendMessage(m)", {"type": kind, **extra})
            if not result.get("ok"):
                raise AssertionError(result)
            return result["data"]
        def state():
            return send("GET_STATE")
        def wait_for(predicate, timeout=25):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                value = state()
                if predicate(value):
                    return value
                panel.wait_for_timeout(150)
            panel.screenshot(path=str(OUT / "timeout.png"), full_page=True)
            print("UI_ERROR", panel.locator("#error").text_content(), "PAGE_ERRORS", errors, "FIXTURE_EVENTS", events[-20:], flush=True)
            raise AssertionError("Timed out: " + json.dumps(state(), ensure_ascii=False))
        panel.fill("[name=interval]", "25")
        saved = wait_for(lambda s: s["settings"]["monitor"]["interval"] == 25)
        checked("editing the interval keeps automatic dates", saved["settings"]["monitor"]["useDefaultDates"])
        next_day = worker.evaluate("""() => {
          const realNow = Date.now;
          const nextDay = realNow() + 2 * 86400000;
          globalThis.restoreFixtureClock = () => { Date.now = realNow; };
          Date.now = () => nextDay;
          return nextDay;
        }""")
        try:
            expected = panel.evaluate("async now => (await import('./rules.js')).defaultDateText(now)", next_day)
            panel.wait_for_function("date => document.querySelector('[name=dateText]').value === date", arg=expected)
            checked("open sidepanel shows the new default range without a reload", expected != saved["settings"]["monitor"]["dateText"])
        finally:
            worker.evaluate("() => restoreFixtureClock()")
        # Home contains both recommendation names, but is not a booking page.
        home=context.new_page();home.goto('https://sports.sjtu.edu.cn/pc/#/')
        response=worker.evaluate('''async()=>{
          const tab=(await chrome.tabs.query({url:'https://sports.sjtu.edu.cn/*'})).find(t=>t.url==='https://sports.sjtu.edu.cn/pc/#/');
          const hello=await chrome.tabs.sendMessage(tab.id,{type:'AGENT_HELLO'});
          await chrome.tabs.sendMessage(tab.id,{type:'AGENT_BIND',runId:'read-only-home-test',deadline:null});
          const base={type:'AGENT_COMMAND',runId:'read-only-home-test',documentId:hello.documentId,venueId:'3466293b-a7d8-45be-a918-8526e3bed4c5',venueName:'东区网球场'};
          const prepare=await chrome.tabs.sendMessage(tab.id,{...base,action:'prepare',commandId:'home-prepare',seq:1});
          const scan=await chrome.tabs.sendMessage(tab.id,{...base,action:'scan',commandId:'home-scan',seq:2,date:'2026-11-01',start:17,end:22});
          return {prepare:prepare.kind,scan:scan.kind};
        }''')
        checked('homepage recommendation names do not count as a venue page',response['prepare']=='wrong_venue')
        checked('page agent refuses scanning homepage before reading dates',response['scan']=='wrong_venue')
        home.close()
        for width in [320, 380, 520]:
            panel.set_viewport_size({"width": width, "height": 1100})
            checked(f"sidepanel {width}px has no horizontal overflow", panel.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            panel.screenshot(path=str(OUT / f"monitor-{width}.png"), full_page=True)
        panel.click("#mode-rush")
        default_times = ["21:00-22:00", "20:00-21:00", "19:00-20:00", "18:00-19:00", "17:00-18:00"]
        time_selectors = "#time-rows select"
        checked("five default priority rows in the requested order", panel.locator(time_selectors).evaluate_all("rows => rows.map(row => row.value)") == default_times)
        checked("default East court 4 and noon release",
                panel.input_value('#rush-form [name=venue]') == "east"
                and panel.input_value('#rush-form [name=scope]') == "all"
                and panel.input_value('#rush-form [name=court]') == "4"
                and panel.input_value('#rush-form [name=releaseTime]') in ("12:00", "12:00:00"))
        panel.screenshot(path=str(OUT / "rush-520.png"), full_page=True)
        panel.set_viewport_size({"width": 320, "height": 1100})
        checked("rush priority controls fit a 320px sidepanel", panel.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        checked("first row cannot move up and last row cannot move down",
                panel.locator(".time-up").first.is_disabled() and panel.locator(".time-down").last.is_disabled())
        panel.locator(".time-up").nth(1).click()
        panel.locator(".time-down").nth(2).click()
        reordered_times = [default_times[i] for i in (1, 0, 3, 2, 4)]
        checked("up and down move rows and keep priority numbers in order",
                panel.locator(time_selectors).evaluate_all("rows => rows.map(row => row.value)") == reordered_times
                and panel.locator(".time-number").all_text_contents() == ["1", "2", "3", "4", "5"])
        wait_for(lambda s: s["settings"]["rush"]["times"] == reordered_times)
        panel.reload()
        panel.wait_for_function("times => Array.from(document.querySelectorAll('#time-rows select'), row => row.value).join(',') === times.join(',')", arg=reordered_times)
        checked("reordered priorities are restored when the sidepanel reloads", True)
        panel.set_viewport_size({"width": 520, "height": 1100})
        panel.click("#mode-monitor")
        # Pre-attach the fixture tab so Playwright intercepts its first navigation
        # as well as subsequent extension-driven reloads.
        school = context.new_page()
        school.goto("https://sports.sjtu.edu.cn/pc/?locale=zh#/apointmentDetails/1/0c6edc93-87ac-41b0-9895-6b66fda93fe5/%25E5%2585%25A8%25E9%2583%25A8/0")
        # Start through the UI, not a direct call to the controller.
        panel.uncheck('[name=venue][value=east]')
        panel.select_option('#monitor-form [name=scope]', "indoor")
        date = panel.evaluate("async()=>{const r=await import('./rules.js');return r.addDays(r.chinaDate(),1)}")
        panel.fill('[name=dateText]', date)
        panel.fill('[name=interval]', "10")
        panel.click("#start")
        value = wait_for(lambda s: s["task"] and s["task"]["autoHalted"])
        checked("real content script clicked and submitted fixture once", sum(e["action"] == "submit" for e in events) == 1)
        checked("monitor continues after confirmed success", value["task"]["active"])
        checked("alarm audio document started", value["task"]["alarming"])
        checked("native sidepanel API configured", panel.evaluate("async()=>{const b=await chrome.sidePanel.getPanelBehavior();const o=await chrome.sidePanel.getOptions({});return b.openPanelOnActionClick && o.path==='sidepanel.html'}"))
        checked("notification API created an alert", panel.evaluate("async()=>Object.hasOwn(await chrome.notifications.getAll(),'sjtu-result')"))
        t=value["task"]
        duplicate={"type":"AGENT_COMMAND","runId":t["id"],"documentId":t["pending"]["documentId"],"seq":t["seq"]-1,"commandId":t["id"]+":"+str(t["seq"]-1),"action":"submit","slot":t["slots"][0]}
        reply=worker.evaluate("async ({tabId,message})=>chrome.tabs.sendMessage(tabId,message)",{"tabId":t["tabs"]["huxiaoming"],"message":duplicate})
        checked("duplicate command reuses response without another click", reply.get("kind")=="submitted" and sum(e["action"]=="submit" for e in events)==1)
        duplicate.update(commandId="old-document",seq=t["seq"]+10,documentId="old-document")
        reply=worker.evaluate("async ({tabId,message})=>chrome.tabs.sendMessage(tabId,message)",{"tabId":t["tabs"]["huxiaoming"],"message":duplicate})
        checked("stale document command rejected", reply.get("error")=="STALE_COMMAND")
        panel.screenshot(path=str(OUT / "monitor-success.png"), full_page=True)
        # Reload the fixture; the old task must reconnect without a duplicate order.
        school.reload()
        panel.wait_for_timeout(1200)
        checked("reload preserves task ID and submit guard", state()["task"]["id"] == value["task"]["id"] and sum(e["action"] == "submit" for e in events) == 1)
        panel.click("#stop-alarm")
        wait_for(lambda s: not s["task"]["alarming"])
        checked("stop alarm leaves monitoring active", state()["task"]["active"])
        # Suspend/restart the actual MV3 service worker in this disposable browser.
        cdp = context.new_cdp_session(panel)
        cdp.send("ServiceWorker.enable")
        cdp.send("ServiceWorker.stopAllWorkers")
        panel.wait_for_timeout(300)
        recovered = state()
        checked("actual service worker restart preserves task and halt", recovered["task"]["id"] == value["task"]["id"] and recovered["task"]["autoHalted"])
        # Close the UI document entirely; the monitoring interval must still run.
        before = sum(e["action"] == "date" for e in events)
        panel.close()
        school.wait_for_timeout(11500)
        checked("monitor runs with sidepanel document closed", sum(e["action"] == "date" for e in events) > before)
        panel = context.new_page();panel.goto(panel_url)
        panel.wait_for_function("() => document.querySelector('[name=dateText]').value.length > 0")
        checked("hand-entered date persists after reopening the sidepanel", panel.locator("[name=dateText]").input_value() == date)
        send("STOP")
        # Short, unfamiliar notices survive in the log without authorizing a retry.
        config["outcome"] = "unknown";school.reload();events.clear()
        raw = state()["settings"]["monitor"]
        send("START", mode="monitor", config=raw)
        wait_for(lambda s: any(e["action"]=="submit" for e in events))
        cdp = context.new_cdp_session(panel);cdp.send("ServiceWorker.enable");cdp.send("ServiceWorker.stopAllWorkers")
        unknown = wait_for(lambda s: s["task"]["autoHalted"])
        checked("unknown outcome halts automatic orders", "不明确" in unknown["task"]["message"])
        checked("unknown outcome submitted fixture only once", sum(e["action"] == "submit" for e in events) == 1)
        texts = [row["text"] for row in unknown["task"]["logs"]]
        checked("brief pre-submit notice is logged with the booking step", "打开下单时的学校提示：校验单号 PRE-42" in texts)
        checked("brief unknown submit notice is logged after worker restart", "提交订单时的学校提示：资格核验返回 E-412，请稍后查看结果" in texts)
        send("STOP")
        # An unrelated selection must not be silently included in an order.
        config["outcome"]="success";school.reload();events.clear()
        school.locator("#selection").evaluate("el=>el.textContent='场地7 19:00-20:00'")
        send("START",mode="monitor",config=raw)
        wait_for(lambda s:s["task"]["status"]=="manual")
        checked("unrelated order selection pauses before booking", not any(e["action"]=="submit" for e in events))
        school.locator("#selection").evaluate("el=>el.textContent=''")
        send("RESUME");wait_for(lambda s:s["task"]["autoHalted"])
        checked("manual clear and resume completes fixture order", sum(e["action"]=="submit" for e in events)==1)
        send("STOP")
        # Both venues contribute to one round's uniqueness decision.
        school.reload();east=context.new_page()
        east.goto("https://sports.sjtu.edu.cn/pc/#/apointmentDetails/1/3466293b-a7d8-45be-a918-8526e3bed4c5/%25E5%2585%25A8%25E9%2583%25A8/0")
        events.clear();both={**raw,"venues":["east","huxiaoming"]}
        send("START",mode="monitor",config=both)
        wait_for(lambda s:len(s["task"]["slots"])==2)
        checked("both venues aggregate before unique-slot decision", not any(e["action"]=="submit" for e in events))
        before=state()['task']['lastCheck'];east.goto('https://sports.sjtu.edu.cn/pc/#/')
        restored=wait_for(lambda s:len(s['task']['slots'])==2 and s['task']['lastCheck']>before and '3466293b-a7d8-45be-a918-8526e3bed4c5' in east.url)
        checked('post-login homepage is immediately returned to East booking page',not any('东区网球场 当前没有可检查' in row['text'] for row in restored['task']['logs']))
        active_worker=context.service_workers[0];east_id=restored['task']['tabs']['east']
        old_doc=active_worker.evaluate("async id=>(await chrome.tabs.sendMessage(id,{type:'AGENT_HELLO'})).documentId",east_id)
        before=restored['task']['lastCheck'];east.evaluate("location.hash='#/'")
        restored=wait_for(lambda s:len(s['task']['slots'])==2 and s['task']['lastCheck']>before and '3466293b-a7d8-45be-a918-8526e3bed4c5' in east.url)
        new_doc=active_worker.evaluate("async id=>(await chrome.tabs.sendMessage(id,{type:'AGENT_HELLO'})).documentId",east_id)
        checked('same-document homepage routing is repaired without reloading the agent',new_doc==old_doc)
        checked('routing repair keeps both venue candidates and makes no order',not any(e['action']=='submit' for e in events))
        new_date=panel.evaluate("async()=>{const r=await import('./rules.js');return r.addDays(r.chinaDate(),2)}")
        send("SAVE_SETTINGS",mode="monitor",config={**both,"dateText":new_date})
        wait_for(lambda s:len(s["task"]["slots"])==2 and all(slot["date"]==new_date for slot in s["task"]["slots"]))
        checked("live monitor edits immediately update both venues", True)
        east.close();stopped=wait_for(lambda s:not s["task"]["active"])
        checked("closing a managed venue tab stops the job", "标签页已关闭" in stopped["task"]["message"])
        # Exercise timed rush with the real wall clock, reload, date discovery and result.
        config.update(outcome="success", rushSlots=[{"hour": 20, "court": 4}, {"hour": 21, "court": 4}])
        east = context.new_page()
        east.goto(panel.evaluate("async () => (await import('./rules.js')).VENUES.east.url"))
        events.clear()
        panel.click("#mode-rush")
        rush = state()["settings"]["rush"]
        rush["releaseTime"] = panel.evaluate("async()=>{const r=await import('./rules.js');return r.chinaTime(Date.now()+4000)}")
        send("START", mode="rush", config=rush)
        panel.wait_for_function("() => Array.from(document.querySelectorAll('.move-time')).every(button => button.disabled)")
        checked("priority buttons are disabled while the rush is active", True)
        result = wait_for(lambda s: not s["task"]["active"], timeout=30)
        checked("timed rush succeeds through real extension", result["task"]["status"] == "success")
        checked("rush used court 4 and the moved first priority over another available time",
                [(e["court"], e["hour"]) for e in events if e["action"] == "submit"] == [("场地4", "20:00")])
        send("STOP_ALARM")
        panel.click("#reset")
        wait_for(lambda s: s["settings"]["rush"]["times"] == default_times)
        checked("restoring rush defaults resets the saved priority order", True)
        # The real content agent recognizes the daily limit and persists cooldown.
        config.pop("rushSlots")
        config["daily"]=True;school.reload();events.clear()
        send("START",mode="monitor",config=raw)
        limited=wait_for(lambda s:s["task"]["status"]=="limited")
        checked("daily limit stops task and persists cooldown", not limited["task"]["active"] and limited["cooldown"]>limited["now"] and not any(e["action"]=="submit" for e in events))
        checked("no uncaught page errors", not errors)
        panel.screenshot(path=str(OUT / "daily-limit.png"), full_page=True)
        send("STOP_ALARM")
        report = {"browser": context.browser.version if context.browser else "Chromium", "platform": "Windows", "fresh_profile": True, "school_requests_intercepted": True, "real_orders_created": 0, "checks": checks, "errors": errors}
        (OUT / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        context.close()
    print("Browser smoke checks:", len(checks), flush=True)

if __name__ == "__main__":
    run()
