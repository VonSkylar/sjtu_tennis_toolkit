import test from "node:test";
import assert from "node:assert/strict";
import {environment} from "./fake-browser.js";
import {VENUES,SCHOOL} from "../rules.js";
test("监控恰好一个候选自动提交一次，成功后继续监控但不再提交",async()=>{
  const e=environment();await e.controller.start("monitor",e.monitor);await e.until(()=>e.controller.task.autoHalted);
  assert.equal(e.submits,1);assert.equal(e.controller.task.active,true);
  for(let n=0;n<15;n++) await e.step();assert.equal(e.submits,1);
});
test("多个候选只报警，不提交；停止报警不停止任务",async()=>{
  const e=environment();e.slots.push({court:"场地7",hour:"19:00"});await e.controller.start("monitor",e.monitor);
  await e.until(()=>e.controller.task.alarming);assert.equal(e.submits,0);
  await e.controller.stopAlarm();assert.equal(e.controller.task.alarming,false);assert.equal(e.controller.task.active,true);
});
test("明确失败的同一场次至少冷却六十秒",async()=>{
  const e=environment();e.outcome="failure";await e.controller.start("monitor",e.monitor);await e.until(()=>e.submits===2);
  const times=e.trace.filter(x=>x.action==="submit").map(x=>x.at);assert.ok(times[1]-times[0]>=60000);
});
test("提交后后台重建只查询结果，不重新提交",async()=>{
  const e=environment();e.outcome="unknown";await e.controller.start("monitor",e.monitor);await e.until(()=>e.submits===1);
  assert.equal(e.session.task.attempt.stage,"result");e.newController();await e.controller.init();await e.until(()=>e.controller.task.autoHalted);
  assert.equal(e.submits,1);assert.equal(e.controller.task.phase,"monitor");
  for(let n=0;n<10;n++) await e.step();assert.equal(e.submits,1);
});
test("抢场优先次序、一次成功停止且保存原绝对截止时间",async()=>{
  const e=environment();await e.controller.start("rush",e.rush);const deadline=e.controller.task.config.deadline;
  await e.until(()=>!e.controller.task.active);assert.equal(e.submits,1);assert.equal(e.controller.task.status,"success");assert.equal(e.controller.task.config.deadline,deadline);
  assert.equal(e.controller.task.attempt.slot.court,"场地6");assert.equal(e.controller.task.attempt.slot.hour,"19:00");
});
test("重复频繁请求每次完整等待一秒，ready 事件不能缩短冷却",async()=>{
  const e=environment();e.frequent=2;await e.controller.start("rush",e.rush);
  await e.until(()=>e.controller.task.phase==="recover");const due=e.controller.task.nextAt;
  await e.controller.ready({tab:{id:Object.values(e.controller.task.tabs)[0]},frameId:0});
  assert.ok([...e.timers.values()].some(x=>x.delay===1000));
  const before=e.trace.filter(x=>x.action==="reload").length;e.setTime(due-1);await e.controller.pump();assert.equal(e.trace.filter(x=>x.action==="reload").length,before);
  await e.until(()=>e.submits===1);
  const detected=e.trace.filter(x=>x.action==="dates").slice(0,2),reloads=e.trace.filter(x=>x.action==="reload");
  for(const request of detected) assert.ok(reloads.find(x=>x.at>request.at).at-request.at>=1000);
});
test("冷却期间手动停止，不再刷新或下单",async()=>{
  const e=environment();e.frequent=2;await e.controller.start("rush",e.rush);await e.until(()=>e.controller.task.phase==="recover");
  const count=e.trace.length;await e.controller.stop();e.setTime(e.now()+10000);await e.controller.pump();assert.equal(e.trace.length,count);assert.equal(e.submits,0);
});
test("每日额度耗尽跨后台重建仍阻止启动",async()=>{
  const e=environment();e.daily=true;await e.controller.start("monitor",e.monitor);await e.until(()=>!e.controller.task.active);
  assert.equal(e.controller.task.status,"limited");assert.equal(e.local.cooldown,Date.parse("2026-11-01T00:10:00+08:00"));
  e.newController();await assert.rejects(()=>e.controller.start("monitor",e.monitor),/额度/);
});
test("休眠恢复已过截止时间，不补抢、不刷新",async()=>{
  const e=environment();await e.controller.start("rush",e.rush);const initial=e.trace.length;e.setTime(e.controller.task.config.deadline+1000);await e.controller.pump();
  assert.equal(e.trace.length,initial);assert.equal(e.controller.task.status,"expired");assert.equal(e.submits,0);
});
test("只允许一个模式，关闭管理标签页停止任务",async()=>{
  const e=environment();await e.controller.start("monitor",e.monitor);await assert.rejects(()=>e.controller.start("rush",e.rush),/已有任务/);await e.step();
  await e.controller.removed(Object.values(e.controller.task.tabs)[0]);assert.equal(e.controller.task.active,false);
});
test("学校页面不能发起控制命令，过期提交授权被拒绝",async()=>{
  const e=environment();await assert.rejects(()=>e.controller.handle({type:"START",mode:"monitor",config:e.monitor},{tab:{id:3},url:"https://sports.sjtu.edu.cn/"}),/来源/);
  await e.controller.start("rush",e.rush);assert.deepEqual(await e.controller.authorize({runId:"old",commandId:"old",documentId:"old"},{tab:{id:9},frameId:0}),{ok:false});
});
test("人工验证暂停，手动继续之前不操作页面",async()=>{
  const e=environment();e.manual=true;await e.controller.start("monitor",e.monitor);await e.until(()=>e.controller.task.status==="manual");
  const count=e.trace.length;await e.step();assert.equal(e.trace.length,count);e.manual=false;await e.controller.resume();await e.until(()=>e.submits===1);
});
test("短间隔有计时器，后台被回收后由 alarm 恢复检查",async()=>{
  const e=environment();e.slots=[];e.monitor.interval=10;await e.controller.start("monitor",e.monitor);await e.until(()=>Boolean(e.controller.task.lastCheck));
  assert.ok([...e.timers.values()].some(x=>x.delay===10000));const saved=e.session.task.nextAt;
  e.newController();await e.controller.init();assert.equal(e.controller.task.nextAt,saved);e.setTime(saved+30000);await e.controller.onAlarm("sjtu-watchdog");
  assert.equal(e.controller.task.active,true);assert.ok(e.trace.filter(x=>x.action==="scan").length>=2);
});
test("并发开始请求只有一个可以创建任务",async()=>{
  const e=environment();const results=await Promise.allSettled([e.controller.start("monitor",e.monitor),e.controller.start("rush",e.rush)]);
  assert.equal(results.filter(x=>x.status==="fulfilled").length,1);assert.equal(results.filter(x=>x.status==="rejected").length,1);
});
test("抢场明确失败时严格按时段和场地优先级尝试",async()=>{
  const e=environment();e.outcome="failure";await e.controller.start("rush",e.rush);await e.until(()=>!e.controller.task.active);
  const selections=e.trace.filter(x=>x.action==="select").map(x=>`${x.slot.hour}|${x.slot.court}`);
  assert.deepEqual(selections,["19:00|场地6","19:00|场地7","20:00|场地6","20:00|场地7","21:00|场地6","21:00|场地7","18:00|场地6","18:00|场地7"]);
  assert.equal(e.submits,8);assert.equal(e.controller.task.status,"failed");
});
test("提交前遇到每日限额仍记录冷却，不当作普通场地失败",async()=>{
  const e=environment();await e.controller.start("monitor",e.monitor);await e.until(()=>e.controller.task.attempt?.stage==="submit");
  const original=e.api.tabs.sendMessage;e.api.tabs.sendMessage=async(id,m)=>m.type==="AGENT_COMMAND"&&m.action==="submit"?{ok:true,documentId:"doc"+id,kind:"daily_limit",clicked:false}:original(id,m);
  await e.step();assert.equal(e.controller.task.active,false);assert.equal(e.controller.task.status,"limited");assert.ok(e.local.cooldown>e.now());assert.equal(e.submits,0);
});
test("人工验证未完成且超过截止时间时停止抢场",async()=>{
  const e=environment();await e.controller.start("rush",e.rush);await e.until(()=>e.submits===1);
  e.controller.task.status="manual";e.setTime(e.controller.task.config.deadline+1000);await e.controller.pump();
  assert.equal(e.controller.task.active,false);assert.equal(e.controller.task.status,"unknown");assert.equal(e.submits,1);
});
test("提交授权绑定当前页面和命令且只能使用一次",async()=>{
  const e=environment();await e.controller.start("rush",e.rush);await e.until(()=>e.controller.task.attempt?.stage==="submit");
  const t=e.controller.task;t.attempt.stage="result";t.pending={action:"submit",tabId:t.tabs.huxiaoming,commandId:"submit1",documentId:"page1",authorized:false};
  const sender={tab:{id:t.tabs.huxiaoming},frameId:0},message={runId:t.id,commandId:"submit1",documentId:"page1"};
  assert.deepEqual(await e.controller.authorize({...message,documentId:"old"},sender),{ok:false});
  assert.deepEqual(await e.controller.authorize(message,sender),{ok:true});assert.deepEqual(await e.controller.authorize(message,sender),{ok:false});
});
test("损坏的配置回退默认值，不阻止插件启动",async()=>{
  const e=environment();e.local.settings={monitor:{interval:"bad"},rush:{times:null}};await e.controller.init();
  assert.equal(e.controller.settings.monitor.interval,20);assert.equal(e.controller.settings.rush.times.length,4);
});
test("旧版过期默认范围自动迁移，开始时计算日期并固定本次任务范围",async()=>{
  const e=environment();
  e.local.settings={monitor:{...e.monitor,dateText:"2026-10-31~2026-11-07",interval:25,autoOrder:false}};
  e.setTime(Date.parse("2026-11-08T20:36:38+08:00"));
  const {monitor}= (await e.controller.snapshot()).settings;
  assert.equal(monitor.dateText,"2026-11-08~2026-11-15");
  assert.equal(monitor.useDefaultDates,true);
  assert.equal(monitor.interval,25);
  assert.equal(monitor.autoOrder,false);
  await e.controller.save("monitor",{...monitor,interval:30});
  e.setTime(Date.parse("2026-11-08T21:00:00+08:00"));
  assert.equal((await e.controller.snapshot()).settings.monitor.dateText,"2026-11-09~2026-11-15");
  const {task}=await e.controller.start("monitor",{...monitor,interval:30});
  assert.equal(task.config.dates[0],"2026-11-09");
  assert.equal(task.config.interval,30);
  e.setTime(Date.parse("2026-11-09T12:00:00+08:00"));
  e.newController();
  assert.equal((await e.controller.snapshot()).settings.monitor.dateText,"2026-11-09~2026-11-15");
  assert.equal((await e.controller.stop()).settings.monitor.dateText,"2026-11-09~2026-11-16");
});
test("手填日期和仍有效的旧范围保持固定，恢复默认后重新滚动",async()=>{
  const e=environment();
  e.setTime(Date.parse("2026-11-08T10:00:00+08:00"));
  e.local.settings={monitor:{...e.monitor,dateText:"2026-11-08~2026-11-14"}};
  assert.equal((await e.controller.snapshot()).settings.monitor.useDefaultDates,false);
  e.setTime(Date.parse("2026-11-15T10:00:00+08:00"));
  e.newController();
  assert.equal((await e.controller.snapshot()).settings.monitor.dateText,"2026-11-08~2026-11-14");
  await e.controller.save("monitor",{...e.monitor,dateText:"2026-11-01,2026-11-03",useDefaultDates:false});
  e.newController();
  assert.equal((await e.controller.snapshot()).settings.monitor.dateText,"2026-11-01,2026-11-03");
  const state=await e.controller.handle({type:"RESET",mode:"monitor"},{url:"chrome-extension://test/sidepanel.html"});
  assert.equal(state.settings.monitor.useDefaultDates,true);
  assert.equal(state.settings.monitor.dateText,"2026-11-15~2026-11-21");
});
test("保留旧版超过 8 天的监控设置，缩短日期后才能启动",async()=>{
  const e=environment();
  const saved={...e.monitor,dateText:"2026-10-31~2026-11-09",interval:25,autoOrder:false};
  e.local.settings={monitor:saved};
  const {monitor}=(await e.controller.snapshot()).settings;
  assert.deepEqual(monitor,{...saved,useDefaultDates:false});
  await assert.rejects(()=>e.controller.save("monitor",monitor),/最多监控 8 天/);
  await assert.rejects(()=>e.controller.start("monitor",monitor),/最多监控 8 天/);
  assert.equal(e.controller.task,null);
  const {task}=await e.controller.start("monitor",{...monitor,dateText:"2026-10-31~2026-11-07"});
  assert.equal(task.config.dates.length,8);
  assert.equal(task.config.interval,25);
  assert.equal(task.config.autoOrder,false);
});
test("页面等待仅接受当前命令，停止后不恢复旧操作",async()=>{
  const e=environment();await e.controller.start("monitor",e.monitor);const t=e.controller.task;
  t.pending={tabId:9,commandId:"cmd",documentId:"doc"};
  const m={type:"AGENT_WAIT",runId:t.id,commandId:"cmd",documentId:"doc",delay:900},sender={tab:{id:9},frameId:0};
  assert.deepEqual(await e.controller.agentWait({...m,documentId:"old"},sender),{ok:false});
  assert.deepEqual(await e.controller.agentWait({...m,delay:30000},sender),{ok:false});
  const pending=e.controller.agentWait(m,sender);await new Promise(resolve=>setImmediate(resolve));
  const timer=[...e.timers.values()].find(x=>x.delay===900);assert.ok(timer);
  await e.controller.stop();timer.fn();assert.deepEqual(await pending,{ok:false});
});
test("首次登录只准备一个场馆，登录完成后再准备其他场馆",async()=>{
  const e=environment();let loggedIn=false;const original=e.api.tabs.sendMessage;
  e.api.tabs.sendMessage=async(id,m)=>m.type==="AGENT_COMMAND"&&m.action==="prepare"&&!loggedIn?{ok:true,documentId:"doc"+id,kind:"login"}:original(id,m);
  await e.controller.start("monitor",{...e.monitor,venues:["east","huxiaoming"]});await e.step();
  assert.equal(Object.keys(e.controller.task.tabs).length,1);assert.equal(e.controller.task.status,"login");
  loggedIn=true;await e.until(()=>e.controller.task.phase==="monitor");assert.equal(Object.keys(e.controller.task.tabs).length,2);
});
test("登录回到首页后必须纠正东区路由再检查日期",async()=>{
  const e=environment(),create=e.api.tabs.create;
  e.api.tabs.create=async data=>{const tab=await create(data);if(data.url.includes(VENUES.east.id)) tab.url=SCHOOL+"/pc/#/";return tab;};
  await e.controller.start("monitor",{...e.monitor,venues:["east","huxiaoming"],autoOrder:false});
  await e.until(()=>e.controller.task.phase==="monitor");
  assert.equal(e.tabs.get(e.controller.task.tabs.east).url,VENUES.east.url);
  assert.ok(e.controller.task.logs.some(x=>x.text.includes("东区网球场")&&x.text.includes("预约页")));
});
test("运行中跳回首页立即纠正，丢弃上轮候选而不误判日期缺失",async()=>{
  const e=environment();await e.controller.start("monitor",{...e.monitor,venues:["east","huxiaoming"],autoOrder:false});
  await e.until(()=>Boolean(e.controller.task.lastCheck));const t=e.controller.task,id=t.tabs.east,taskId=t.id;
  e.tabs.get(id).url=SCHOOL+"/pc/#/";
  await e.controller.ready({tab:{id},frameId:0,url:SCHOOL+"/pc/#/"});
  await e.step();assert.equal(e.tabs.get(id).url,VENUES.east.url);assert.equal(t.id,taskId);assert.equal(e.submits,0);
  assert.ok(!t.logs.some(x=>x.text.includes("东区网球场 当前没有可检查")));
});
test("订单提交后的结果页不会被纠正回场馆或再次提交",async()=>{
  const e=environment();await e.controller.start("rush",e.rush);await e.until(()=>e.submits===1);
  const t=e.controller.task,id=t.tabs.huxiaoming,url=SCHOOL+"/pc/#/orderDetails/1";e.tabs.get(id).url=url;
  await e.until(()=>!t.active);assert.equal(t.status,"success");assert.equal(e.tabs.get(id).url,url);assert.equal(e.submits,1);
});
