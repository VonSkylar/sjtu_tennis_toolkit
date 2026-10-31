import {Controller} from "../controller.js";
import {monitorDefaults,RUSH_DEFAULTS} from "../rules.js";
export function environment() {
  let time=Date.parse("2026-10-31T11:59:58+08:00"),nextId=1,timerId=0;
  const local={},session={},tabs=new Map(),trace=[],timers=new Map(),alarms=new Map();
  const storage=store=>({get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys]).map(k=>[k,structuredClone(store[k])])),set:async values=>Object.assign(store,structuredClone(values))});
  const env={now:()=>time,setTime:n=>{time=n;},local,session,tabs,trace,timers,alarms,
    outcome:"success",slots:[{court:"场地6",hour:"19:00"}],daily:false,frequent:0,manual:false,submits:0};
  const api={
    storage:{local:storage(local),session:storage(session)},
    runtime:{getURL:path=>"chrome-extension://test/"+path,sendMessage:async m=>m.type==="AUDIO_START"?{ok:true}:{}},
    alarms:{create:async(name,value)=>alarms.set(name,value),clear:async name=>alarms.delete(name)},
    notifications:{create:async()=>{},clear:async()=>{}},
    offscreen:{hasDocument:async()=>false,createDocument:async()=>{},closeDocument:async()=>{}},
    tabs:{
      query:async()=>[...tabs.values()],get:async id=>{if(!tabs.has(id)) throw Error("closed");return tabs.get(id);},
      create:async data=>{const t={...data,id:nextId++};tabs.set(t.id,t);trace.push({action:"create",at:time});return t;},
      update:async(id,data)=>Object.assign(tabs.get(id),data),reload:async id=>trace.push({action:"reload",tabId:id,at:time}),
      sendMessage:async(id,m)=>{
        if(m.type==="AGENT_HELLO") return {ok:true,documentId:"doc"+id,url:tabs.get(id)?.url};
        if(m.type!=="AGENT_COMMAND") return {ok:true};
        trace.push({action:m.action,at:time,commandId:m.commandId,slot:m.slot});
        const response={ok:true,documentId:"doc"+id};
        if(env.daily) return {...response,kind:"daily_limit"};
        if(m.action==="dates"&&env.frequent-->0) return {...response,kind:"frequent",message:"请求过于频繁"};
        if(env.manual) return {...response,kind:"manual",message:"请人工验证"};
        if(m.action==="scan") return {...response,kind:"ready",slots:env.slots};
        if(m.action==="dates") return {...response,kind:"ready",ready:true,targetFound:true};
        if(m.action==="grid") return {...response,kind:"ready",ready:true};
        if(m.action==="select") return {...response,kind:"selected"};
        if(m.action==="accept") return {...response,kind:"accepted"};
        if(m.action==="submit") {
          const permit=await env.controller.authorize({runId:m.runId,commandId:m.commandId,documentId:m.documentId},{tab:{id},frameId:0});
          if(!permit.ok) return {...response,kind:"unknown",clicked:false};
          env.submits++;return {...response,kind:"submitted",clicked:true};
        }
        if(m.action==="result") return {...response,kind:env.outcome,message:env.outcome};
        return {...response,kind:"ready"};
      }
    }
  };
  env.api=api;
  env.newController=()=>{
    const c=new Controller(api,{now:()=>time,setTimer:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimer:id=>timers.delete(id)});env.controller=c;return c;
  };
  env.newController();
  env.monitor={...monitorDefaults(time),venues:["huxiaoming"],scope:"indoor",dateText:"2026-11-01"};
  env.rush={...structuredClone(RUSH_DEFAULTS)};
  env.step=async()=>{time=Math.max(time,env.controller.task.nextAt);await env.controller.pump();};
  env.until=async(condition,limit=100)=>{for(let i=0;i<limit&&!condition();i++) await env.step();if(!condition()) throw Error("condition not reached: "+JSON.stringify(env.controller.task));};
  return env;
}
