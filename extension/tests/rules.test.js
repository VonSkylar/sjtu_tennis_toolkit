import test from "node:test";
import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {chinaDate,chinaTime,addDays,parseDates,defaultDateText,allowedCourts,courtOrder,parseTimeRange,validateConfig,RUSH_DEFAULTS,monitorDefaults,cooldownUntil,autoOrderCandidate,slotKey,isVenueUrl,VENUES,SCHOOL} from "../rules.js";
const at=s=>Date.parse(s+"+08:00");
test("预约页按路由和场馆 ID 判断，首页推荐文字或查询参数不能代替",()=>{
  assert.equal(isVenueUrl(VENUES.east.url,"east"),true);
  assert.equal(isVenueUrl(VENUES.huxiaoming.url,"east"),false);
  for(const url of [SCHOOL+"/pc/#/",SCHOOL+"/pc/?venue="+VENUES.east.id+"#/",SCHOOL+"/pc/#/orderDetails/"+VENUES.east.id,VENUES.east.url.replace(SCHOOL,"https://example.com")]) assert.equal(isVenueUrl(url,"east"),false);
});
test("北京时间不依赖主机时区，跨月跨年与闰年正确",()=>{
  assert.equal(chinaDate(Date.parse("2026-10-31T16:01:00Z")),"2026-11-01");
  assert.equal(chinaTime(Date.parse("2026-10-31T04:00:00Z")),"12:00:00");
  assert.equal(addDays("2026-12-28",7),"2027-01-04");assert.equal(addDays("2028-02-28",1),"2028-02-29");
  assert.equal(cooldownUntil(at("2026-10-31T23:59:59")),at("2026-11-01T00:10:00"));
});
test("日期列表去重保留输入顺序、范围与边界校验",()=>{
  assert.deepEqual(parseDates("2026-11-03；2026-11-01,2026-11-03"),["2026-11-03","2026-11-01"]);
  assert.equal(parseDates("2026-11-01 至 2026-11-14").length,14);
  for(const input of ["","2026-02-30","2026-11-14~2026-11-01","2026-11-01~2026-11-15"]) assert.throws(()=>parseDates(input));
});
test("默认日期范围与 Python 原行为逐项一致",()=>{
  const cases=["2026-10-31T00:01:00","2026-10-31T11:59:59","2026-10-31T12:00:00","2026-10-31T20:59:59","2026-10-31T21:00:00","2026-12-31T23:59:59"];
  const script="import json,sys,datetime as d\nfrom sjtu_tennis_toolkit.config import default_date_range_text,parse_dates,rush_allowed_courts,rush_court_attempt_order\na=json.loads(sys.stdin.read())\nprint(json.dumps([default_date_range_text(d.datetime.fromisoformat(x)) for x in a]))";
  const out=spawnSync("python",["-X","utf8","-c",script],{cwd:fileURLToPath(new URL("../../",import.meta.url)),input:JSON.stringify(cases),encoding:"utf8"});
  assert.equal(out.status,0,out.stderr);const expected=JSON.parse(out.stdout);
  assert.deepEqual(cases.map(s=>defaultDateText(at(s))),expected);
});
test("场地范围与场地优先级",()=>{
  assert.deepEqual(allowedCourts("huxiaoming","indoor"),[6,7]);assert.deepEqual(allowedCourts("huxiaoming","outdoor"),[1,2,3,4,5,8]);
  assert.equal(allowedCourts("east","indoor").length,8);assert.deepEqual(courtOrder("huxiaoming","indoor",7),[7,6]);
  assert.throws(()=>courtOrder("huxiaoming","indoor",1));assert.throws(()=>allowedCourts("missing"));
});
test("抢场完整保留四个时段、默认值及当日一分钟窗口",()=>{
  const now=at("2026-10-31T10:00:00"),c=validateConfig("rush",RUSH_DEFAULTS,now);
  assert.equal(c.targetDate,"2026-11-07");assert.equal(c.releaseAt,at("2026-10-31T12:00:00"));assert.equal(c.deadline-c.releaseAt,60000);
  assert.deepEqual(c.times,RUSH_DEFAULTS.times);assert.equal(c.court,6);
  assert.throws(()=>validateConfig("rush",{...RUSH_DEFAULTS,times:["19:00-20:00","19:00-20:00"]},now));
  assert.throws(()=>validateConfig("rush",{...RUSH_DEFAULTS,times:Array(8).fill("19:00-20:00")},now));
  assert.throws(()=>validateConfig("rush",{...RUSH_DEFAULTS,releaseTime:"25:00:00"},now));
  assert.equal(parseTimeRange("7:00~8:00"),"07:00-08:00");assert.throws(()=>parseTimeRange("21:00-23:00"));
});
test("监控间隔和唯一候选冷却规则",()=>{
  const now=at("2026-10-31T10:00:00"),config=validateConfig("monitor",monitorDefaults(now),now),slot={venue:"huxiaoming",date:"2026-11-01",hour:"19:00",court:"场地6"};
  assert.equal(config.interval,20);assert.equal(config.autoOrder,true);
  assert.throws(()=>validateConfig("monitor",{...monitorDefaults(now),interval:9},now));
  assert.equal(autoOrderCandidate([slot],config,false,{},now),slot);
  assert.equal(autoOrderCandidate([slot,slot],config,false,{},now),null);
  assert.equal(autoOrderCandidate([slot],config,true,{},now),null);
  assert.equal(autoOrderCandidate([slot],config,false,{[slotKey(slot)]:now-59999},now),null);
  assert.equal(autoOrderCandidate([slot],config,false,{[slotKey(slot)]:now-60000},now),slot);
});
