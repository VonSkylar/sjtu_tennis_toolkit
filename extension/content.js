/* Runs in Chrome's isolated world. No page globals, credentials, or API secrets. */
(() => {
  "use strict";
  if(globalThis.__sjtuAgent) return;
  globalThis.__sjtuAgent=true;
  const P=globalThis.SJTU_PROBES, docId=crypto.randomUUID();
  let binding=null, highest=0, busy=false,executing=null;
  const cache=new Map();
  const norm=s=>String(s||"").replace(/\s+/g,"").trim();
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>4&&r.height>4&&s.visibility!=="hidden"&&s.display!=="none";};
  const all=()=>Array.from(document.querySelectorAll("body *")).filter(visible);
  const args=value=>({...value,geom:P.geometry});
  // Hidden school tabs can heavily throttle DOM timers. Request bounded waits
  // from the extension worker instead; this also rechecks cancellation.
  const sleep=async ms=>{
    const reply=await chrome.runtime.sendMessage({type:"AGENT_WAIT",runId:executing?.runId,commandId:executing?.commandId,documentId:docId,delay:ms});
    if(!reply?.ok||!reply.data?.ok) throw Error("STALE_COMMAND");
  };
  const notices=()=>norm(P.notice(args({})));
  const failure=()=>{const t=notices();return /已被预定|请重新选择时段|预约失败|下单失败|提交失败|无法预约|已被预约|库存不足|请(?:先)?选择场地/.test(t)?t:"";};
  const success=()=>{const t=notices();return /预约成功|预订成功|下单成功|提交成功|订单提交成功/.test(t)?t:"";};
  const labels=date=>{const [y,m,d]=date.split("-");return [date,`${m}月${d}日`,`${Number(m)}月${Number(d)}日`];};
  function health() {
    const text=norm(document.body?.innerText);
    if(/每日请求超过限制|请求超过限制/.test(text)) return {kind:"daily_limit",message:"学校系统提示每日请求超过限制"};
    if(text.includes("请求过于频繁")) return {kind:"frequent",message:"请求过于频繁，等待一秒后重试"};
    if(/统一身份认证|登录jAccount|校内人员登录/.test(text)) return {kind:"login",message:"请在学校页面完成登录"};
    const captcha=Array.from(document.querySelectorAll(".verifybox,.verify-box,.captcha-popup,.verifybox-top,[class*='captcha-dialog']")).some(visible);
    if(captcha||/拖动滑块|请完成安全验证|请完成验证|向右滑动完成验证/.test(text)) return {kind:"manual",message:"请在学校页面完成人工验证，再点击检查并继续"};
    return {kind:"ready"};
  }
  function guard(message,{deadline=true}={}) {
    if(!binding||binding.id!==message.runId||binding.cancelled||message.documentId!==docId) throw Error("STALE_COMMAND");
    if(deadline&&binding.deadline&&Date.now()>=binding.deadline) throw Error("DEADLINE");
  }
  function click(el,message,point) {
    guard(message);if(!el||!visible(el)) throw Error("目标元素不可见");
    el.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,view:window,clientX:point?.x||0,clientY:point?.y||0}));
  }
  function button(text,root=document) {
    return Array.from(root.querySelectorAll("button,[role=button],.el-button,.ant-btn")).filter(visible).filter(el=>norm(el.innerText).includes(text)&&!el.disabled&&!/disabled/.test(String(el.className))).at(-1);
  }
  function dialog() {return Array.from(document.querySelectorAll(".el-dialog,[role=dialog],.ant-modal,.van-dialog")).filter(visible).find(el=>/预订须知|预定须知|本人已认真阅读|自愿接受/.test(norm(el.innerText)));}
  function selectionSummary(slot) {
    const range=`${slot.hour}-${String(Number(slot.hour.slice(0,2))+1).padStart(2,"0")}:00`,entries=new Set();
    // Check a small order-summary container, not the whole body (which contains all court labels).
    for(let el of all().filter(el=>el.children.length===0&&/\d{2}:00-\d{2}:00/.test(norm(el.innerText).replace(/[~～—至]/g,"-")))) {
      for(let depth=0;el&&depth<5;depth++,el=el.parentElement) {
        if(el===document.body||el.tagName==="TABLE") break;
        const text=norm(el.innerText).replace(/[~～—至]/g,"-");
        if(text.length>400) break;
        // There are exactly eight courts. Whitespace normalization can join
        // "场地6 19:00" into "场地619:00", so do not consume the hour digits.
        const courts=[...new Set(text.match(/场地[1-8]/g)||[])];
        if(courts.length===1) {for(const time of text.match(/\d{2}:00-\d{2}:00/g)||[]) entries.add(`${courts[0]}|${time}`);break;}
      }
    }
    return {matches:entries.size===1&&entries.has(`${slot.court}|${range}`),hasAny:entries.size>0};
  }
  const selected=slot=>selectionSummary(slot).matches;
  function clearNotices() {for(const el of document.querySelectorAll(".el-message,.ant-message,.van-toast,.toast,[role=alert]")) el.remove();}
  async function selectDate(date,message) {
    const wanted=labels(date).map(norm);
    const candidates=all().filter(el=>wanted.some(l=>norm(el.innerText).includes(l))).sort((a,b)=>norm(a.innerText).length-norm(b.innerText).length);
    const target=candidates.find(el=>norm(el.innerText).length<80);
    if(!target) return false;
    click(target,message);await sleep(900);guard(message);return true;
  }
  async function perform(m) {
    guard(m,{deadline:m.action!=="result"});
    const h=health();
    if(m.action==="prepare") {
      if(h.kind==="login") {const target=all().find(el=>norm(el.innerText)==="校内人员登录");if(target) click(target,m);return h;}
      if(h.kind!=="ready") return h;
      const hasVenue=location.href.includes(m.venueId)||norm(document.body.innerText).includes(m.venueName);
      return hasVenue?{kind:"ready"}:{kind:"wrong_venue"};
    }
    if(m.action==="result") {
      const end=Date.now()+Math.max(0,Math.min(3100,m.timeout??3100));
      do {
        guard(m,{deadline:false});const bad=failure(),good=success();
        if(bad) return {kind:"failure",message:bad};
        if(good) return {kind:"success",message:good};
        if(health().kind==="manual") return {kind:"manual",message:health().message};
        await sleep(120);
      }while(Date.now()<end);
      return {kind:"unknown",message:"提交后没有看到明确成功或失败提示，请核对学校订单"};
    }
    if(h.kind!=="ready") return m.action==="submit"?{...h,clicked:false}:h;
    if(m.action==="dates") return {kind:"ready",...P.dates(args({labels:labels(m.date).map(norm),readyCount:7}))};
    if(m.action==="scan") {
      if(!await selectDate(m.date,m)) return {kind:"not_open",message:`${m.date} 尚未出现在日期条`};
      const state=health();if(state.kind!=="ready") return state;
      const result=P.scan(args({targetHours:Array.from({length:m.end-m.start},(_,i)=>`${String(m.start+i).padStart(2,"0")}:00`)}));
      return result.error?{kind:"loading",message:result.error}:{kind:"ready",slots:result.slots};
    }
    if(m.action==="date") return await selectDate(m.date,m)?{kind:"ready"}:{kind:"not_open"};
    if(m.action==="grid") return {kind:"ready",...P.grid(args({targetHour:m.hour}))};
    if(m.action==="select") {
      binding.submitted=false;
      clearNotices();P.scroll(args({targetHour:m.slot.hour}));await sleep(100);guard(m);
      if(selected(m.slot)) return {kind:"selected"};
      if(selectionSummary(m.slot).hasAny) return {kind:"manual",message:"订单栏已有其他场次，请清空后点击检查并继续"};
      let cell=P.cell(args({targetCourt:m.slot.court,targetHour:m.slot.hour}));
      if(!["available","selected"].includes(cell.state)) return {kind:"unavailable",message:cell.reason};
      if(cell.x<4||cell.x>innerWidth-4||cell.y<4||cell.y>innerHeight-4) {
        const candidate=all().find(el=>{const r=el.getBoundingClientRect();return r.width>=25&&r.width<=120&&r.height>=20&&r.height<=90&&Math.abs(r.left+r.width/2-cell.x)<2&&Math.abs(r.top+r.height/2-cell.y)<2;});
        candidate?.scrollIntoView({block:"center",inline:"center"});await sleep(80);guard(m);
        cell=P.cell(args({targetCourt:m.slot.court,targetHour:m.slot.hour}));
      }
      const el=document.elementFromPoint(cell.x,cell.y);
      if(!el) return {kind:"loading",message:"目标格子不在可点击区域"};
      click(el,m,cell);
      for(let n=0;n<12;n++) {await sleep(100);guard(m);if(selected(m.slot)) return {kind:"selected"};if(failure()) return {kind:"failure",message:failure()};}
      return {kind:"unavailable",message:"点击后未能在订单栏确认目标场次"};
    }
    if(m.action==="open_order") {
      if(!selected(m.slot)) return {kind:"unavailable",message:"订单栏与目标场次不一致"};
      if(!dialog()) {const el=button("立即下单");if(!el) return {kind:"loading",message:"等待立即下单按钮"};click(el,m);await sleep(180);}
      return failure()?{kind:"failure",message:failure()}:health();
    }
    if(m.action==="accept") {
      for(let n=0;n<20;n++) {
        guard(m);const box=dialog();
        if(box) {
          const input=box.querySelector('input[type="checkbox"]');
          const checked=input?.checked||Array.from(box.querySelectorAll('.is-checked,[aria-checked="true"]')).some(visible);
          if(checked) return {kind:"accepted"};
          const label=Array.from(box.querySelectorAll("label")).find(el=>visible(el)&&/本人已认真阅读|自愿接受|同意/.test(norm(el.innerText)));
          const target=label||input||Array.from(box.querySelectorAll(".el-checkbox,.ant-checkbox-wrapper")).find(visible);
          if(target) {if(visible(target)) click(target,m);else {guard(m);target.click();}}
        }
        await sleep(100);
      }
      return {kind:"manual",message:"未能确认预订须知已勾选，请检查学校页面"};
    }
    if(m.action==="submit") {
      if(binding.submitted) return {kind:"unknown",clicked:false,message:"当前页面已执行过提交，不重复操作"};
      if(!selected(m.slot)) return {kind:"unavailable",clicked:false,message:"提交前目标场次校验失败"};
      const box=dialog(),input=box?.querySelector('input[type="checkbox"]');
      if(!box||!(input?.checked||Array.from(box.querySelectorAll('.is-checked,[aria-checked="true"]')).some(visible))) return {kind:"manual",clicked:false,message:"请核对预订须知"};
      const target=button("提交订单",box);if(!target) return {kind:"manual",clicked:false,message:"未找到可用的提交订单按钮"};
      // Obtain fresh authorization immediately before the irreversible click.
      const permit=await chrome.runtime.sendMessage({type:"AUTHORIZE_SUBMIT",runId:m.runId,commandId:m.commandId,documentId:docId});
      guard(m);if(!permit?.ok||!permit.data?.ok) throw Error("STALE_COMMAND");
      binding.submitted=true;click(target,m);
      return {kind:"submitted",clicked:true};
    }
    throw Error("未知页面操作");
  }
  chrome.runtime.onMessage.addListener((m,sender,respond)=>{
    if(sender.id!==chrome.runtime.id||sender.tab) return;
    if(m.type==="AGENT_HELLO") {respond({ok:true,documentId:docId,url:location.href,health:health()});return;}
    if(m.type==="AGENT_CANCEL") {if(binding?.id===m.runId) binding.cancelled=true;respond({ok:true});return;}
    if(m.type==="AGENT_BIND") {
      if(binding?.id!==m.runId) {binding={id:m.runId,deadline:m.deadline,cancelled:false,submitted:false};highest=0;cache.clear();}
      respond({ok:true,documentId:docId});return;
    }
    if(m.type!=="AGENT_COMMAND") return;
    if(cache.has(m.commandId)) {respond(cache.get(m.commandId));return;}
    if(m.documentId!==docId||m.runId!==binding?.id||binding?.cancelled||m.seq<=highest||busy) {respond({ok:false,error:"STALE_COMMAND",documentId:docId});return;}
    highest=m.seq;busy=true;executing=m;
    perform(m).then(result=>{
      const response={ok:true,documentId:docId,...result};cache.set(m.commandId,response);
      if(cache.size>64) cache.delete(cache.keys().next().value);respond(response);
    }).catch(e=>respond({ok:false,error:e.message,documentId:docId})).finally(()=>{busy=false;});return true;
  });
  chrome.runtime.sendMessage({type:"AGENT_READY",documentId:docId}).catch(()=>{});
})();
