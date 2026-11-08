import {SCHOOL,VENUES,RUSH_DEFAULTS,monitorDefaults,defaultDateText,validateConfig,chinaTime,chinaDate,cooldownUntil,courtOrder,filterSlots,slotKey,slotText,autoOrderCandidate,taskExpired,isVenueUrl} from "./rules.js";

const clone=value=>structuredClone(value);
const uid=()=>crypto.randomUUID();
const automaticMonitorDefaults=now=>({...monitorDefaults(now),useDefaultDates:true});
const orderNoticeStages={select:"选场",open_order:"打开下单",accept:"确认须知",submit:"提交订单",result:"核对结果"};
export class Controller {
  constructor(api,{now=()=>Date.now(),setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}={}) {
    this.api=api;this.now=now;this.setTimer=setTimer;this.clearTimer=clearTimer;
    this.task=null;this.settings=null;this.timer=null;this.busy=false;this.initializing=null;this.starting=false;this.stopping=false;
  }
  async init() {
    if(!this.initializing) this.initializing=(async()=>{
      const [local,session]=await Promise.all([this.api.storage.local.get(["settings","cooldown"]),this.api.storage.session.get("task")]);
      const now=this.now();
      const defaults={monitor:automaticMonitorDefaults(now),rush:clone(RUSH_DEFAULTS)};
      this.settings={...defaults,...local.settings};
      let migrated=false;
      for(const mode of ["monitor","rush"]) {
        const saved=this.settings[mode];
        try {
          // Keep longer ranges from older versions visible for the user to edit.
          const config=validateConfig(mode,saved,now,{maxMonitorDates:14});
          if(mode==="monitor"&&saved.useDefaultDates===undefined) {
            // Old settings did not distinguish auto-filled dates from manual dates.
            const {dates}=config,last=dates.at(-1);
            saved.useDefaultDates=(dates.length===7||dates.length===8)
              &&saved.dateText===`${dates[0]}~${last}`&&last<chinaDate(now);
            migrated=true;
          }
        } catch {this.settings[mode]=defaults[mode];}
      }
      if(migrated) await this.api.storage.local.set({settings:this.settings});
      this.cooldown=Number.isFinite(local.cooldown)?local.cooldown:0;this.task=session.task||null;
      if(this.task?.active) this.schedule(Math.max(this.now(),this.task.nextAt||0));
    })();
    return this.initializing;
  }
  alive(t) {return this.task===t&&t.active;}
  check(t) {if(!this.alive(t)) throw Error("CANCELLED");}
  log(t,text) {
    const last=t.logs.at(-1);if(last?.text===text&&this.now()-last.at<3000) return;
    t.logs.push({at:this.now(),time:chinaTime(this.now()),text});t.logs=t.logs.slice(-180);
  }
  async persist(t=this.task) {
    if(this.task!==t) return;
    await this.api.storage.session.set({task:clone(t)});
    this.broadcast();
  }
  broadcast() {this.api.runtime.sendMessage({type:"STATE_CHANGED"}).catch(()=>{});}
  async snapshot() {
    await this.init();
    const now=this.now(),settings=clone(this.settings),task=clone(this.task);
    if(settings.monitor.useDefaultDates) {
      settings.monitor.dateText=task?.active&&task.mode==="monitor"?task.config.dateText:defaultDateText(now);
    }
    return {settings,task,cooldown:this.cooldown,now};
  }
  async save(mode,raw) {
    await this.init();const config=validateConfig(mode,raw,this.now());
    if(this.task?.active&&this.task.mode===mode&&mode==="rush") throw Error("抢场运行中不能修改配置，请先停止");
    if(this.task?.active&&this.task.mode===mode&&this.task.attempt) throw Error("正在处理订单，待结果明确后再修改条件");
    const settings=clone(raw);
    if(mode==="monitor") settings.useDefaultDates=raw.useDefaultDates===true;
    this.settings[mode]=settings;await this.api.storage.local.set({settings:this.settings});
    if(this.task?.active&&mode==="monitor"&&this.task.mode===mode) {
      const t=this.task;t.config=config;t.revision++;t.cursor={};this.resetRound(t);t.phase="monitor";
      await this.stopAlarm();this.log(t,"监控条件已更新，立即重新检查");t.nextAt=this.now();await this.persist(t);this.schedule(t.nextAt);
    }
    this.broadcast();return config;
  }
  async start(mode,raw) {
    await this.init();if(this.task?.active||this.starting||this.stopping) throw Error("已有任务正在运行或切换，请先等待停止完成");
    if(this.cooldown>this.now()) throw Error("今日请求额度已达上限，请等待冷却结束");
    const now=this.now();
    if(mode==="monitor"&&raw?.useDefaultDates===true) raw={...raw,dateText:defaultDateText(now)};
    const config=validateConfig(mode,raw,now);if(mode==="rush"&&config.deadline<=now) throw Error("今天的抢场窗口已结束，请修改开始时间或明天再试");
    this.starting=true;
    try {
    await this.save(mode,raw);await this.stopAlarm();
    const t={id:uid(),mode,config,active:true,status:"preparing",message:"准备预约页面",phase:"prepare",tabs:{},cursor:{},roundIndex:0,roundSlots:[],roundChecked:[],roundMisses:0,seq:0,revision:0,logs:[],slots:[],attempt:null,attempts:{},autoHalted:false,alarming:false,nextAt:this.now(),createdAt:this.now(),lastCheck:null};
    this.task=t;this.log(t,`开始${mode==="rush"?"定时抢场":"空场监控"}，所有日期和时间均为北京时间`);
    await this.persist(t);this.schedule(t.nextAt);return this.snapshot();
    }finally {this.starting=false;}
  }
  async stop(message="任务已手动停止") {
    await this.init();this.stopping=true;const t=this.task;
    try {
    if(t) {t.active=false;t.status="stopped";t.message=message;this.log(t,message);await this.persist(t);
      await Promise.allSettled(Object.values(t.tabs).map(tabId=>this.api.tabs.sendMessage(tabId,{type:"AGENT_CANCEL",runId:t.id})));
    }
    this.cancelSchedule();await this.stopAlarm();return this.snapshot();
    }finally {this.stopping=false;}
  }
  cancelSchedule() {
    if(this.timer!==null) this.clearTimer(this.timer);this.timer=null;
    this.api.alarms.clear("sjtu-tick").catch(()=>{});this.api.alarms.clear("sjtu-watchdog").catch(()=>{});
  }
  schedule(at) {
    const t=this.task;if(!t?.active) return;
    if(this.timer!==null) this.clearTimer(this.timer);this.timer=null;
    const delay=Math.max(0,at-this.now());
    // Chrome 120 supports 30-second alarms. Short active steps have a timer,
    // with a persisted deadline and alarm fallback if the worker is reclaimed.
    this.api.alarms.create("sjtu-tick",{when:Math.max(at,this.now()+30000)}).catch(()=>{});
    this.api.alarms.create("sjtu-watchdog",{periodInMinutes:0.5}).catch(()=>{});
    if(delay<30000) this.timer=this.setTimer(()=>{this.timer=null;this.pump();},delay);
  }
  async wake() {await this.init();const t=this.task;if(t?.active) this.schedule(Math.min(t.nextAt||this.now(),this.now()));}
  async onAlarm(name) {if(name.startsWith("sjtu-")) {await this.init();if(this.task?.active) await this.pump();}}
  async removed(tabId) {await this.init();if(this.task?.active&&Object.values(this.task.tabs).includes(tabId)) await this.stop("预约标签页已关闭，任务停止");}
  async ready(sender) {
    await this.init();if(sender.frameId!==0) return;
    const t=this.task;if(t?.active&&Object.values(t.tabs).includes(sender.tab?.id)&&t.status!=="manual") {
      // React to post-login / SPA routing immediately, but never shorten a
      // mandatory cooldown or redirect a potentially submitted order's result.
      if(t.phase!=="recover"&&t.attempt?.stage!=="result") {t.routeDirty=true;t.nextAt=this.now();await this.persist(t);}
      this.schedule(t.nextAt||this.now());
    }
  }
  async authorize(m,sender) {
    await this.init();const t=this.task,p=t?.pending;
    if(!t?.active||t.id!==m.runId||!t.attempt||t.attempt.stage!=="result"||t.autoHalted||taskExpired(t,this.now())||sender.frameId!==0||p?.tabId!==sender.tab?.id||p.commandId!==m.commandId||p.documentId!==m.documentId||p.action!=="submit"||p.authorized) return {ok:false};
    p.authorized=true;await this.persist(t);return {ok:this.alive(t)};
  }
  async agentWait(m,sender) {
    await this.init();const t=this.task;
    const valid=()=>this.alive(t)&&t.id===m.runId&&sender.frameId===0&&t.pending?.tabId===sender.tab?.id&&t.pending?.commandId===m.commandId&&t.pending?.documentId===m.documentId;
    if(!Number.isInteger(m.delay)||m.delay<0||m.delay>1000||!valid()) return {ok:false};
    await new Promise(resolve=>this.setTimer(resolve,m.delay));
    return {ok:valid()};
  }
  async resume() {
    await this.init();const t=this.task;if(!t?.active) throw Error("没有运行中的任务");
    if(taskExpired(t,this.now())&&t.attempt?.stage!=="result") {await this.finish(t,"expired","抢场窗口已结束");return this.snapshot();}
    t.status="running";t.message="重新检查学校页面";t.nextAt=this.now();await this.persist(t);this.schedule(t.nextAt);return this.snapshot();
  }
  async openVenue(key="huxiaoming") {
    const venue=VENUES[key];if(!venue) throw Error("场馆无效");
    const tabs=await this.api.tabs.query({url:SCHOOL+"/*"});const tab=tabs.find(x=>isVenueUrl(x.url,key));
    if(tab) {await this.api.tabs.update(tab.id,{active:true});return tab.id;}
    return (await this.api.tabs.create({url:venue.url,active:true})).id;
  }
  async ensureTab(t,key) {
    this.check(t);let id=t.tabs[key];
    if(id) {try {await this.api.tabs.get(id);return id;}catch {this.check(t);throw Error("预约标签页已关闭");}}
    const existing=await this.api.tabs.query({url:SCHOOL+"/*"});this.check(t);
    const tab=existing.find(x=>isVenueUrl(x.url,key))||await this.api.tabs.create({url:VENUES[key].url,active:Object.keys(t.tabs).length===0});
    this.check(t);t.tabs[key]=tab.id;await this.persist(t);return tab.id;
  }
  async send(tabId,message,timeout=7000) {
    let timer;try {return await Promise.race([this.api.tabs.sendMessage(tabId,message),new Promise((_,reject)=>{timer=this.setTimer(()=>reject(Error("页面响应超时")),timeout);})]);}
    finally {this.clearTimer(timer);}
  }
  async call(t,key,action,data={}) {
    this.check(t);const tabId=await this.ensureTab(t,key);let hello;
    try {hello=await this.send(tabId,{type:"AGENT_HELLO"});}catch {return {kind:"loading",message:"等待学校页面加载或完成登录"};}
    this.check(t);
    if(action!=="result"&&(hello.health?.kind||"ready")==="ready"&&!isVenueUrl(hello.url,key)) return {kind:"wrong_venue",clicked:false};
    await this.send(tabId,{type:"AGENT_BIND",runId:t.id,deadline:t.mode==="rush"?t.config.deadline:null});this.check(t);
    const seq=++t.seq,commandId=`${t.id}:${seq}`;
    t.pending={action,tabId,commandId,documentId:hello.documentId,authorized:false};await this.persist(t);this.check(t);
    try {
      const result=await this.send(tabId,{type:"AGENT_COMMAND",runId:t.id,commandId,seq,documentId:hello.documentId,action,...data,venueId:VENUES[key].id,venueName:VENUES[key].name});
      this.check(t);
      if(result?.documentId!==hello.documentId) return {kind:"loading",message:"页面已刷新，等待重新连接"};
      if(t.attempt&&result.orderNotices?.length) {
        const logged=t.attempt.loggedNotices??=[];
        for(const {action:stage,text} of result.orderNotices) {
          const line=`${orderNoticeStages[stage]}时的学校提示：${text}`;
          if(logged.includes(line)) continue;
          logged.push(line);
          this.log(t,line);
        }
      }
      if(!result.ok) {if(result.error==="DEADLINE") return {kind:"expired"};return {kind:"loading",message:result.error||"页面操作未完成"};}
      return result;
    }catch(error) {this.check(t);return {kind:"loading",message:"页面已跳转或暂未响应，等待重新连接"};}
  }
  async finish(t,status,message) {
    if(!this.alive(t)) return;t.active=false;t.status=status;t.message=message;this.log(t,message);
    await this.persist(t);this.cancelSchedule();
    await Promise.allSettled(Object.values(t.tabs).map(tabId=>this.api.tabs.sendMessage(tabId,{type:"AGENT_CANCEL",runId:t.id})));
    await this.notify(t,message,false);
  }
  async notify(t,message,sound=true) {
    if(this.task!==t||t.status==="stopped") return;
    try {await this.api.notifications.create("sjtu-result",{type:"basic",iconUrl:this.api.runtime.getURL("icons/icon128.png"),title:"网球预约助手",message});}catch {this.log(t,"系统通知不可用，请查看插件状态和学校页面");}
    if(sound) {
      try {
        if(this.task!==t||t.status==="stopped") return;
        if(!await this.api.offscreen.hasDocument()) await this.api.offscreen.createDocument({url:"offscreen.html",reasons:["AUDIO_PLAYBACK"],justification:"发现目标空场时播放可手动停止的提示音"});
        if(this.task!==t||t.status==="stopped") return;
        const playing=await this.api.runtime.sendMessage({type:"AUDIO_START",target:"audio"});
        if(!playing?.ok) throw Error("音频未能播放");t.alarming=true;
      }catch {this.log(t,"提示音不可用，已保留系统通知和候选空场");}
    }
    await this.persist(t);
  }
  async stopAlarm() {
    try {if(await this.api.offscreen.hasDocument()) {await this.api.runtime.sendMessage({type:"AUDIO_STOP",target:"audio"});await this.api.offscreen.closeDocument();}}catch {}
    if(this.task) {this.task.alarming=false;await this.persist(this.task);}
    try {await this.api.notifications.clear("sjtu-result");}catch {}
  }
  resetRound(t) {t.roundIndex=0;t.roundSlots=[];t.roundChecked=[];t.roundMisses=0;}
  async health(t,result,key) {
    if(result.kind==="wrong_venue") {
      this.check(t);
      this.log(t,`${VENUES[key].name} 页面已跳离预约路由，正在返回该场馆预约页`);
      if(t.mode==="monitor"&&!t.attempt) {this.resetRound(t);t.slots=[];}
      t.message=`正在恢复${VENUES[key].name}预约页`;
      await this.api.tabs.update(t.tabs[key],{url:VENUES[key].url});this.check(t);
      t.nextAt=this.now()+1000;return false;
    }
    if(result.kind==="daily_limit") {
      this.cooldown=cooldownUntil(this.now());await this.api.storage.local.set({cooldown:this.cooldown});
      await this.finish(t,"limited",`每日请求额度已达上限，冷却至 ${chinaDate(this.cooldown)} ${chinaTime(this.cooldown).slice(0,5)}`);return false;
    }
    if(result.kind==="expired") {await this.finish(t,"expired","抢场窗口已结束");return false;}
    if(result.kind==="manual") {t.status="manual";t.message=result.message;this.log(t,result.message);t.nextAt=this.now()+30000;await this.notify(t,result.message,false);return false;}
    if(result.kind==="login") {t.status="login";t.message="请在学校页面完成登录，成功后自动继续";if(t.phase!=="prepare") {t.resumePhase=t.phase;t.phase="prepare";}if(t.mode==="monitor"&&!t.attempt) {this.resetRound(t);t.slots=[];}t.nextAt=this.now()+1500;return false;}
    if(result.kind==="frequent") {
      this.log(t,result.message);t.recover={key,phase:t.phase};t.phase="recover";t.status="running";t.message="请求频繁，等待一秒后刷新";t.nextAt=this.now()+1000;return false;
    }
    if(result.kind==="loading") {t.message=result.message||"等待学校页面加载";t.nextAt=this.now()+500;return false;}
    return true;
  }
  async pump() {
    await this.init();const t=this.task;if(!t?.active||this.busy) return;
    if(t.nextAt>this.now()) {this.schedule(t.nextAt);return;}
    this.busy=true;
    try {
      if(taskExpired(t,this.now())&&t.attempt?.stage!=="result") {await this.finish(t,"expired","抢场窗口已结束");return;}
      if(t.status==="manual") {
        if(taskExpired(t,this.now())&&t.attempt?.stage==="result") {await this.unknown(t,"验证未完成且抢场窗口已结束，请核对学校订单");return;}
        t.nextAt=this.now()+30000;return;
      }
      t.nextAt=this.now()+100;
      if(t.routeDirty&&t.phase!=="prepare"&&t.phase!=="recover"&&t.attempt?.stage!=="result") {
        if(!await this.ensureBookingPages(t)) return;
        t.routeDirty=false;
      }
      if(t.phase==="prepare") await this.prepare(t);
      else if(t.phase==="recover") {const {key,phase}=t.recover;this.check(t);await this.api.tabs.reload(t.tabs[key]);this.check(t);t.phase=phase;t.nextAt=this.now()+400;}
      else if(t.phase==="attempt") await this.orderStep(t);
      else if(t.mode==="monitor") await this.monitorStep(t);
      else await this.rushStep(t);
    }catch(error) {
      if(this.alive(t)&&error.message!=="CANCELLED") {
        if(t.attempt?.stage==="result") await this.unknown(t,"提交期间页面连接中断，请核对学校订单");
        else {this.log(t,`本步未完成：${error.message}`);t.message=error.message;t.nextAt=this.now()+1000;}
      }
    }finally {
      this.busy=false;
      if(this.task===t) {
        if(t.routeDirty&&t.phase!=="recover"&&t.status!=="manual"&&t.attempt?.stage!=="result"&&t.nextAt>this.now()+1500) t.nextAt=this.now();
        await this.persist(t);
      }
      if(this.task?.active) this.schedule(this.task.nextAt);
    }
  }
  async ensureBookingPages(t) {
    for(const key of t.mode==="monitor"?t.config.venues:[t.config.venue]) {
      const result=await this.call(t,key,"prepare");
      if(!await this.health(t,result,key)) return false;
    }
    return true;
  }
  async prepare(t) {
    if(!await this.ensureBookingPages(t)) return;
    t.routeDirty=false;
    t.status="running";t.message="预约页面已就绪";
    t.phase=t.resumePhase||(t.mode==="monitor"?"monitor":"wait");delete t.resumePhase;
    t.nextAt=this.now();this.log(t,"预约页面已就绪");
  }
  async monitorStep(t) {
    const config=t.config;
    if(t.roundIndex===0&&!await this.ensureBookingPages(t)) return;
    if(t.roundIndex<config.venues.length) {
      const key=config.venues[t.roundIndex],cursor=(t.cursor[key]||0)%config.dates.length,date=config.dates[cursor],revision=t.revision;
      const result=await this.call(t,key,"scan",{date,start:config.start,end:config.end});
      if(t.revision!==revision) return;
      if(!await this.health(t,result,key)) return;
      t.cursor[key]=(cursor+1)%config.dates.length;
      if(result.kind==="not_open") {
        t.roundMisses++;if(t.roundMisses<config.dates.length) return;
        this.log(t,`${VENUES[key].name} 当前没有可检查的目标日期`);
      }else {
        t.roundSlots.push(...filterSlots(result.slots||[],key,config.scope).map(slot=>({...slot,venue:key,date})));
        t.roundChecked.push({venue:key,date});
      }
      t.roundIndex++;t.roundMisses=0;return;
    }
    t.slots=[...new Map(t.roundSlots.map(slot=>[slotKey(slot),slot])).values()];t.lastCheck=this.now();
    const alertKey=t.slots.map(slotKey).sort().join(";");
    if(t.slots.length&&alertKey!==t.lastAlertKey) {t.lastAlertKey=alertKey;this.log(t,`发现 ${t.slots.length} 个符合条件的空场`);await this.notify(t,slotText(t.slots[0])+(t.slots.length>1?` 等 ${t.slots.length} 个空场`:""));this.check(t);}
    if(!t.slots.length) {t.lastAlertKey="";this.log(t,"本轮未发现符合条件的空场");}
    const candidate=autoOrderCandidate(t.slots,config,t.autoHalted,t.attempts,this.now());
    if(candidate) {t.attempts[slotKey(candidate)]=this.now();this.beginAttempt(t,candidate);return;}
    t.message=t.autoHalted?"监控中；自动下单已停止，请核对订单":`监控中，本轮 ${t.slots.length} 个空场`;
    this.resetRound(t);t.nextAt=this.now()+config.interval*1000;
  }
  beginAttempt(t,slot) {t.attempt={slot,stage:"select",createdAt:this.now(),stepAt:this.now()};t.phase="attempt";t.message=`正在尝试：${slotText(slot)}`;this.log(t,t.message);}
  async rushStep(t) {
    const c=t.config,key=c.venue;
    if(t.phase==="wait") {
      const remaining=c.releaseAt-this.now();
      if(remaining>0) {t.status="waiting";t.message=`等待 ${c.releaseTime} 放场`;
        // Long waits sleep normally. Only the final 20 seconds use short steps.
        t.nextAt=remaining>25000?c.releaseAt-20000:Math.min(c.releaseAt,this.now()+1000);return;
      }
      t.status="running";t.phase="reload";t.timeIndex=0;t.courtIndex=0;return;
    }
    if(t.phase==="reload") {
      this.log(t,"刷新预约页面，检查目标日期");t.phase="dates";t.reloadAt=this.now();await this.persist(t);this.check(t);
      await this.api.tabs.reload(t.tabs[key]);this.check(t);t.nextAt=this.now()+300;return;
    }
    if(t.phase==="dates") {
      const result=await this.call(t,key,"dates",{date:c.targetDate});if(!await this.health(t,result,key)) return;
      if(!result.ready) {t.message="等待日期条加载";t.nextAt=this.now()+300;return;}
      if(!result.targetFound) {t.phase="reload";t.nextAt=this.now();return;}
      const selected=await this.call(t,key,"date",{date:c.targetDate});if(!await this.health(t,selected,key)) return;
      if(selected.kind!=="ready") {t.nextAt=this.now()+200;return;}
      t.phase="grid";return;
    }
    if(t.phase==="grid") {
      if(t.timeIndex>=c.times.length) {await this.finish(t,"failed","没有抢到目标时段，已尝试全部优先时段和场地");return;}
      const courts=courtOrder(key,c.scope,c.court);
      if(t.courtIndex>=courts.length) {t.timeIndex++;t.courtIndex=0;return;}
      const hour=c.times[t.timeIndex].slice(0,5),result=await this.call(t,key,"grid",{hour});
      if(!await this.health(t,result,key)) return;
      if(!result.ready) {t.message=result.reason||"等待场地图加载";t.nextAt=this.now()+200;return;}
      this.beginAttempt(t,{venue:key,date:c.targetDate,hour,court:`场地${courts[t.courtIndex]}`});return;
    }
  }
  async rejectAttempt(t,message) {
    this.log(t,message);t.attempt=null;
    if(t.mode==="rush") {t.courtIndex++;t.phase="grid";t.nextAt=this.now();}
    else {this.resetRound(t);t.phase="monitor";t.nextAt=this.now()+t.config.interval*1000;t.message="自动下单未成功，继续监控";}
  }
  async unknown(t,message) {
    t.autoHalted=true;this.log(t,message);
    if(t.mode==="rush") await this.finish(t,"unknown",message+"；已停止，避免重复下单");
    else {t.attempt=null;this.resetRound(t);t.phase="monitor";t.message="提交结果不明确；继续监控，自动下单已停止";t.nextAt=this.now()+t.config.interval*1000;await this.notify(t,t.message);}
  }
  async orderStep(t) {
    const a=t.attempt,key=a.slot.venue;
    if(a.stage==="result") {
      const result=await this.call(t,key,"result",{timeout:3100});
      if(result.kind==="loading"&&this.now()-a.submitAt<12000) {t.nextAt=this.now()+300;return;}
      if(result.kind==="success") {
        t.autoHalted=true;this.log(t,`学校页面已确认下单成功：${slotText(a.slot)}`);
        if(t.mode==="rush") {await this.finish(t,"success",`已确认下单成功：${slotText(a.slot)}`);await this.notify(t,t.message);}
        else {t.attempt=null;this.resetRound(t);t.phase="monitor";t.message="已确认下单成功；继续监控，自动下单已停止";t.nextAt=this.now()+t.config.interval*1000;await this.notify(t,t.message);}
        return;
      }
      if(result.kind==="failure") {await this.rejectAttempt(t,`提交失败：${result.message}`);return;}
      if(result.kind==="manual") {t.status="manual";t.message=result.message;t.nextAt=this.now()+30000;await this.notify(t,result.message,false);return;}
      await this.unknown(t,result.message||"提交后没有明确结果，请核对学校订单");return;
    }
    const action={select:"select",open:"open_order",accept:"accept",submit:"submit"}[a.stage];
    if(!action) throw Error("订单步骤无效");
    if(action==="submit") {
      // Commit before sending: recovery can inspect a result but must never
      // resend this submission if the worker dies between send and response.
      a.stage="result";a.submitAt=this.now();await this.persist(t);this.check(t);
    }
    const result=await this.call(t,key,action,{slot:a.slot});
    if(action==="submit") {
      if(result.clicked===false) {
        if(result.kind==="unknown") {await this.unknown(t,result.message||"页面提示已经提交，请核对订单");}
        else if(["manual","login","frequent","daily_limit","expired","wrong_venue"].includes(result.kind)) {
          a.stage=result.kind==="manual"?"accept":"select";await this.health(t,result,key);
        }else await this.rejectAttempt(t,result.message||"提交前校验未通过，未点击提交");
      }
      // Any lost reply after sending is treated as potentially submitted.
      return;
    }
    if(!await this.health(t,result,key)) return;
    if(["unavailable","failure"].includes(result.kind)) {await this.rejectAttempt(t,result.message||"目标格子不可用");return;}
    const expected={select:"selected",open_order:"ready",accept:"accepted"}[action];
    if(result.kind!==expected) {t.nextAt=this.now()+200;return;}
    a.stage={select:"open",open_order:"accept",accept:"submit"}[action];a.stepAt=this.now();
  }
  async handle(m,sender={}) {
    if(m.type==="AGENT_READY") {await this.ready(sender);return {ok:true};}
    if(m.type==="AUTHORIZE_SUBMIT") return this.authorize(m,sender);
    if(m.type==="AGENT_WAIT") return this.agentWait(m,sender);
    // Only extension pages may issue user controls; school pages cannot start jobs.
    if(!String(sender.url||"").startsWith(this.api.runtime.getURL(""))) throw Error("无效的控制消息来源");
    switch(m.type) {
      case "GET_STATE": return this.snapshot();
      case "SAVE_SETTINGS": await this.save(m.mode,m.config);return this.snapshot();
      case "START": return this.start(m.mode,m.config);
      case "STOP": return this.stop();
      case "STOP_ALARM": await this.stopAlarm();return this.snapshot();
      case "RESUME": return this.resume();
      case "OPEN_VENUE": await this.openVenue(m.venue);return this.snapshot();
      case "RESET": await this.save(m.mode,m.mode==="rush"?clone(RUSH_DEFAULTS):automaticMonitorDefaults(this.now()));return this.snapshot();
      default: throw Error("未知控制命令");
    }
  }
}
