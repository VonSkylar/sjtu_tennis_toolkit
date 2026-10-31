import {VENUES,RUSH_DEFAULTS,allowedCourts,addDays,chinaDate,chinaTime} from "./rules.js";
const $=id=>document.getElementById(id),monitor=$("monitor-form"),rush=$("rush-form");
let mode="monitor",snapshot=null,initialized=false,saving=null,requestBusy=false,lastLogs="",lastSlots="";
const f=(form,name)=>form.elements.namedItem(name);
function error(text="") {$("error").textContent=text;$("error").hidden=!text;}
async function send(type,extra={}) {
  const result=await chrome.runtime.sendMessage({type,...extra});
  if(!result?.ok) throw Error(result?.error||"插件后台暂未响应");return result.data;
}
function options(select,start,end) {for(let h=start;h<=end;h++) {const o=document.createElement("option");o.value=h;o.textContent=`${String(h).padStart(2,"0")}:00`;select.append(o);}}
options(f(monitor,"start"),7,21);options(f(monitor,"end"),8,22);
function timeRow(value) {
  const row=document.createElement("div");row.className="time-row";
  const number=document.createElement("span");number.className="time-number";
  const select=document.createElement("select");select.name="timeRange";
  for(let h=7;h<22;h++) {const o=document.createElement("option");o.value=`${String(h).padStart(2,"0")}:00-${String(h+1).padStart(2,"0")}:00`;o.textContent=o.value;select.append(o);}
  select.value=value;select.setAttribute("aria-label","备选时段");
  const remove=document.createElement("button");remove.type="button";remove.className="remove-time";remove.textContent="×";remove.setAttribute("aria-label","删除这个时段");
  remove.addEventListener("click",()=>{row.remove();numberRows();changed();});row.append(number,select,remove);return row;
}
function numberRows() {const rows=[...$("time-rows").children];rows.forEach((row,i)=>{row.querySelector(".time-number").textContent=i+1;row.querySelector("select").setAttribute("aria-label",`第 ${i+1} 优先时段`);row.querySelector("button").disabled=rows.length===1||snapshot?.task?.active;});$("add-time").disabled=rows.length>=7||snapshot?.task?.active;}
function updateCourts(preferred=f(rush,"court").value) {
  const venue=f(rush,"venue").value,scope=f(rush,"scope");
  scope.disabled=venue==="east"||Boolean(snapshot?.task?.active&&snapshot.task.mode==="rush");
  if(venue==="east") scope.value="all";
  const courts=allowedCourts(venue,scope.value),select=f(rush,"court");select.replaceChildren(...courts.map(n=>{const o=document.createElement("option");o.value=n;o.textContent=`场地 ${n}`;return o;}));select.value=courts.includes(Number(preferred))?preferred:courts[0];
}
function apply(settings) {
  const m=settings.monitor,r=settings.rush;
  for(const input of monitor.querySelectorAll('[name="venue"]')) input.checked=m.venues.includes(input.value);
  for(const name of ["scope","dateText","start","end","interval"]) f(monitor,name).value=m[name];f(monitor,"autoOrder").checked=m.autoOrder;
  for(const name of ["venue","scope","releaseTime"]) f(rush,name).value=r[name];updateCourts(r.court);
  $("time-rows").replaceChildren(...r.times.map(timeRow));numberRows();
}
function config() {
  if(mode==="monitor") return {venues:[...monitor.querySelectorAll('[name="venue"]:checked')].map(el=>el.value),scope:f(monitor,"scope").value,dateText:f(monitor,"dateText").value,start:Number(f(monitor,"start").value),end:Number(f(monitor,"end").value),interval:Number(f(monitor,"interval").value),autoOrder:f(monitor,"autoOrder").checked};
  const time=f(rush,"releaseTime").value;
  return {venue:f(rush,"venue").value,scope:f(rush,"scope").value,court:Number(f(rush,"court").value),releaseTime:time.length===5?time+":00":time,times:[...$("time-rows").querySelectorAll("select")].map(el=>el.value)};
}
function setMode(next) {
  mode=next;monitor.hidden=mode!=="monitor";rush.hidden=mode!=="rush";
  for(const m of ["monitor","rush"]) {$("mode-"+m).classList.toggle("selected",m===mode);$("mode-"+m).setAttribute("aria-pressed",String(m===mode));}
  chrome.storage.local.set({uiMode:mode});error();if(snapshot) render(snapshot);
}
const statusNames={preparing:"准备中",login:"等待登录",manual:"需要操作",running:"运行中",waiting:"等待放场",stopped:"已停止",expired:"已结束",failed:"未抢到",success:"已下单",unknown:"请核对订单",limited:"请求已达上限"};
function render(state) {
  snapshot=state;const t=state.task,active=Boolean(t?.active),cooldown=state.cooldown>Date.now();
  $("status-badge").textContent=cooldown?"冷却中":t?statusNames[t.status]||"运行中":"未开始";
  $("status-badge").className="badge"+(active&&!['manual','login'].includes(t.status)?" running":["unknown","limited","failed"].includes(t?.status)?" error":"");
  $("status-text").textContent=cooldown?`每日请求额度已用完，${chinaDate(state.cooldown)} 00:10 后可再试`:t?.message||"设置条件后即可开始";
  $("status-detail").textContent=active?`${t.mode==="monitor"?"监控":"抢场"}任务运行中 · 侧边栏可关闭`:"关闭侧边栏不会停止任务";
  $("start").textContent=mode==="monitor"?"开始监控":"开始抢场";$("start").disabled=active||cooldown||requestBusy;
  $("stop").disabled=!active||requestBusy;$("resume").hidden=!(active&&t.status==="manual");
  $("stop-alarm").disabled=!t?.alarming;$("reset").disabled=active&&(t.mode==="rush"||Boolean(t.attempt));
  const lockRush=active&&t.mode==="rush",lockMonitor=active&&Boolean(t.attempt);
  for(const el of rush.querySelectorAll("input,select,button")) el.disabled=lockRush;
  for(const el of monitor.querySelectorAll("input,select,textarea")) el.disabled=lockMonitor;
  f(rush,"scope").disabled=lockRush||f(rush,"venue").value==="east";
  f(monitor,"scope").disabled=lockMonitor||!monitor.querySelector('[name="venue"][value="huxiaoming"]').checked;
  numberRows();
  const slots=t?.slots||[],slotSignature=JSON.stringify(slots);$("slot-count").textContent=`${slots.length} 个`;
  if(slotSignature!==lastSlots||!initialized) {
    lastSlots=slotSignature;$("slots").replaceChildren();
    if(!slots.length) {const p=document.createElement("p");p.className="empty";p.textContent="符合条件的场次会显示在这里。";$("slots").append(p);}
    for(const slot of slots) {const row=document.createElement("div");row.className="slot";const info=document.createElement("div"),title=document.createElement("strong"),date=document.createElement("small"),time=document.createElement("span");title.textContent=`${VENUES[slot.venue].name} · ${slot.court}`;date.textContent=slot.date;time.textContent=`${slot.hour}–${String(Number(slot.hour.slice(0,2))+1).padStart(2,"0")}:00`;info.append(title,date);row.append(info,time);$("slots").append(row);}
  }
  const logs=t?.logs||[],signature=JSON.stringify(logs);
  if(signature!==lastLogs) {lastLogs=signature;const box=$("logs"),follow=box.scrollHeight-box.scrollTop-box.clientHeight<40;box.replaceChildren();
    if(!logs.length) {const p=document.createElement("p");p.className="empty";p.textContent="准备就绪，等待开始。";box.append(p);}
    for(const entry of logs) {const row=document.createElement("div");row.className="log-line";const time=document.createElement("time"),text=document.createElement("span");time.textContent=entry.time;text.textContent=entry.text;row.append(time,text);box.append(row);}if(follow) box.scrollTop=box.scrollHeight;
  }
  $("last-check").textContent=t?.lastCheck?`最近 ${chinaTime(t.lastCheck)}`:"尚未检查";tickClock();
}
function tickClock() {
  $("clock").textContent=`北京时间 ${chinaTime()}`;$("target-date").textContent=addDays(chinaDate(),7);
  const t=snapshot?.task;
  if(t?.active&&t.mode==="rush") {const before=t.config.releaseAt>Date.now(),ms=(before?t.config.releaseAt:t.config.deadline)-Date.now(),seconds=Math.max(0,Math.ceil(ms/1000));$("status-detail").textContent=before?`距放场 ${Math.floor(seconds/3600)}:${String(Math.floor(seconds/60)%60).padStart(2,"0")}:${String(seconds%60).padStart(2,"0")}`:`剩余尝试时间 ${seconds} 秒`;}
}
async function refresh() {
  try {const state=await send("GET_STATE");if(!initialized) {apply(state.settings);initialized=true;const stored=await chrome.storage.local.get("uiMode");setMode(stored.uiMode==="rush"?"rush":"monitor");}render(state);}catch(e) {error(e.message);}
}
async function act(type,extra={}) {requestBusy=true;if(snapshot) render(snapshot);error();try {const state=await send(type,extra);render(state);return state;}catch(e){error(e.message);return null;}finally{requestBusy=false;if(snapshot) render(snapshot);}}
function changed() {
  if(!initialized) return;clearTimeout(saving);const changedMode=mode,changedConfig=config();
  saving=setTimeout(async()=>{try{const state=await send("SAVE_SETTINGS",{mode:changedMode,config:changedConfig});error();render(state);}catch(e){error(e.message);}},500);
}
for(const form of [monitor,rush]) {form.addEventListener("submit",e=>e.preventDefault());form.addEventListener("input",changed);form.addEventListener("change",changed);}
f(rush,"venue").addEventListener("change",()=>updateCourts());f(rush,"scope").addEventListener("change",()=>updateCourts());
for(const m of ["monitor","rush"]) $("mode-"+m).addEventListener("click",()=>setMode(m));
$("add-time").addEventListener("click",()=>{const used=new Set([...$("time-rows").querySelectorAll("select")].map(el=>el.value));let value;for(let h=7;h<22;h++){const candidate=`${String(h).padStart(2,"0")}:00-${String(h+1).padStart(2,"0")}:00`;if(!used.has(candidate)){value=candidate;break;}}if(value&&used.size<7){$("time-rows").append(timeRow(value));numberRows();changed();}});
$("start").addEventListener("click",()=>{clearTimeout(saving);act("START",{mode,config:config()});});
$("stop").addEventListener("click",()=>act("STOP"));$("resume").addEventListener("click",()=>act("RESUME"));$("stop-alarm").addEventListener("click",()=>act("STOP_ALARM"));
$("open-venue").addEventListener("click",()=>act("OPEN_VENUE",{venue:mode==="rush"?f(rush,"venue").value:"huxiaoming"}));
$("reset").addEventListener("click",async()=>{clearTimeout(saving);const state=await act("RESET",{mode});if(state) {apply(state.settings);render(state);}});
chrome.runtime.onMessage.addListener(message=>{if(message.type==="STATE_CHANGED") refresh();});
setInterval(tickClock,1000);setInterval(refresh,3000);refresh();
