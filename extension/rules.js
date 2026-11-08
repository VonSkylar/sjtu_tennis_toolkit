import "./booking-rules.js";
import "./route.js";
const bookingRules = globalThis.SJTU_BOOKING_RULES;
export const {
  schoolOrigin:SCHOOL,
  openHour:OPEN_HOUR,
  closeHour:CLOSE_HOUR,
  bookingDaysAhead:RUSH_TARGET_DAYS_AHEAD,
  rushAttemptWindowSeconds:RUSH_ATTEMPT_WINDOW_SECONDS,
  maxRushTimeSlots:MAX_RUSH_TIME_SLOTS,
  minCheckIntervalSeconds:MIN_CHECK_INTERVAL_SECONDS,
} = bookingRules;
export const MAX_MONITOR_DATES = RUSH_TARGET_DAYS_AHEAD + 1;
export const VENUES = Object.fromEntries(Object.entries(bookingRules.venues).map(([key,venue])=>[
  key, {...venue,key,url:`${SCHOOL}/pc/?locale=zh#/apointmentDetails/1/${venue.id}/%25E5%2585%25A8%25E9%2583%25A8/0`},
]));
export function isVenueUrl(url,key) {return Boolean(VENUES[key]&&globalThis.SJTU_ROUTE.matches(url,VENUES[key].id));}
export const RUSH_DEFAULTS = Object.freeze({
  ...bookingRules.rushDefaults,
  releaseTime:`${String(bookingRules.releaseHour).padStart(2,"0")}:00:00`,
});
export const scopeNames = {all:"全部都要", indoor:"只要室内场", outdoor:"只要室外场"};
const allCourts = Array.from({length:bookingRules.courtCount},(_,i)=>i+1);
const indoorCourts = bookingRules.huxiaomingIndoorCourts;
const outdoorCourts = allCourts.filter(court=>!indoorCourts.includes(court));
const formatter = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Shanghai", year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"});
export function chinaParts(now=Date.now()) {
  return Object.fromEntries(formatter.formatToParts(new Date(now)).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));
}
export function chinaDate(now=Date.now()) {const p=chinaParts(now); return `${p.year}-${p.month}-${p.day}`;}
export function chinaTime(now=Date.now()) {const p=chinaParts(now);return `${p.hour}:${p.minute}:${p.second}`;}
export function addDays(date, days) {
  const value=new Date(`${validateDate(date)}T12:00:00+08:00`); value.setTime(value.getTime()+days*86400000);
  return chinaDate(value.getTime());
}
export function validateDate(text) {
  const s=String(text).trim();
  if(!/^\d{4}-\d{2}-\d{2}$/.test(s) || !Number.isFinite(Date.parse(`${s}T00:00:00+08:00`)) || chinaDate(Date.parse(`${s}T00:00:00+08:00`))!==s) throw Error("日期格式应为有效的 YYYY-MM-DD");
  return s;
}
export function parseDates(text,maxDates=MAX_MONITOR_DATES) {
  const values=new Set();
  const parts=String(text).trim().replace(/\s*(~|～|至|到)\s*/g,"~").split(/[,，;；\s]+/).filter(Boolean);
  if(!parts.length) throw Error("请填写监控日期");
  for(const part of parts) {
    const range=part.split(/[~～]/);
    if(range.length>2) throw Error("日期范围格式应为 开始日期~结束日期");
    let first=validateDate(range[0]), last=validateDate(range[1]||range[0]);
    if(first>last) throw Error("日期范围的结束日期不能早于开始日期");
    for(let date=first;date<=last;date=addDays(date,1)) {
      values.add(date);
      if(values.size>maxDates) throw Error(`一次最多监控 ${maxDates} 天`);
    }
  }
  return [...values];
}
export function defaultDateText(now=Date.now()) {
  const hour=Number(chinaParts(now).hour),startTomorrow=hour>=CLOSE_HOUR-1;
  const first=addDays(chinaDate(now),startTomorrow?1:0);
  const visibleDays=!startTomorrow&&hour>=bookingRules.releaseHour?MAX_MONITOR_DATES:RUSH_TARGET_DAYS_AHEAD;
  return `${first}~${addDays(first,visibleDays-1)}`;
}
export function monitorDefaults(now=Date.now()) {
  return {venues:Object.keys(VENUES),scope:"all",dateText:defaultDateText(now),
    start:bookingRules.defaultMonitorStartHour,end:CLOSE_HOUR,interval:bookingRules.defaultCheckIntervalSeconds,autoOrder:true};
}
export function allowedCourts(venue,scope="all") {
  if(!VENUES[venue]) throw Error("请选择有效场馆");
  if(!Object.hasOwn(scopeNames,scope)) throw Error("请选择有效场地范围");
  if(venue!=="huxiaoming"||scope==="all") return [...allCourts];
  return scope==="indoor"?[...indoorCourts]:[...outdoorCourts];
}
export function courtOrder(venue,scope,preferred) {const courts=allowedCourts(venue,scope);const n=Number(preferred);if(!courts.includes(n)) throw Error("优先场地不在当前场地范围内");return [n,...courts.filter(c=>c!==n)];}
export function parseTimeRange(value) {
  const match=String(value).trim().match(/^(\d{1,2}):00\s*[-~]\s*(\d{1,2}):00$/);
  if(!match) throw Error("时段格式应为 HH:00-HH:00");
  const start=Number(match[1]),end=Number(match[2]);
  if(start<OPEN_HOUR||end>CLOSE_HOUR||end!==start+1) throw Error(`抢场时段须为 ${courtHoursText} 内连续一小时`);
  return `${String(start).padStart(2,"0")}:00-${String(end).padStart(2,"0")}:00`;
}
export function releaseTimestamp(time,now=Date.now()) {
  if(!/^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/.test(String(time))) throw Error("开始抢场时间应为 HH:MM:SS");
  return Date.parse(`${chinaDate(now)}T${time}+08:00`);
}
const courtHoursText=`${String(OPEN_HOUR).padStart(2,"0")}:00 至 ${String(CLOSE_HOUR).padStart(2,"0")}:00`;
export function rushTargetDate(now=Date.now()) {return addDays(chinaDate(now),RUSH_TARGET_DAYS_AHEAD);}
export function validateConfig(mode,value,now=Date.now(),{maxMonitorDates=MAX_MONITOR_DATES}={}) {
  if(!value||typeof value!=="object") throw Error("配置格式不正确");
  const scope=value.scope||"all";allowedCourts(mode==="rush"?value.venue:"east",scope);
  if(mode==="monitor") {
    const venues=[...new Set(value.venues||[])];if(!venues.length||venues.some(v=>!VENUES[v])) throw Error("至少选择一个有效场馆");
    const start=Number(value.start),end=Number(value.end),interval=Number(value.interval);
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<OPEN_HOUR||end>CLOSE_HOUR||end<=start) throw Error(`监控时间应在 ${courtHoursText} 内，结束晚于开始`);
    if(!Number.isSafeInteger(interval)||interval<MIN_CHECK_INTERVAL_SECONDS||interval>2147483) throw Error(`检查间隔须为不小于 ${MIN_CHECK_INTERVAL_SECONDS} 的整数秒`);
    return {venues,scope,dateText:String(value.dateText).trim(),dates:parseDates(value.dateText,maxMonitorDates),start,end,interval,autoOrder:value.autoOrder===true};
  }
  if(mode!=="rush") throw Error("模式无效");
  const venue=value.venue;courtOrder(venue,scope,value.court);
  if(!Array.isArray(value.times)||!value.times.length||value.times.length>MAX_RUSH_TIME_SLOTS) throw Error(`请设置 1 至 ${MAX_RUSH_TIME_SLOTS} 个抢场时段`);
  const times=value.times.map(parseTimeRange);if(new Set(times).size!==times.length) throw Error("抢场时段不能重复");
  const releaseAt=releaseTimestamp(value.releaseTime,now);
  return {venue,scope:venue==="east"?"all":scope,court:Number(value.court),times,releaseTime:value.releaseTime,
    targetDate:rushTargetDate(now),releaseAt,deadline:releaseAt+RUSH_ATTEMPT_WINDOW_SECONDS*1000};
}
export function cooldownUntil(now=Date.now()) {return Date.parse(`${addDays(chinaDate(now),1)}T${bookingRules.rateLimitRetryTime}:00+08:00`);}
export function slotKey(slot) {return `${slot.venue}|${slot.date}|${slot.hour}|${slot.court}`;}
export function slotText(slot) {return `${VENUES[slot.venue].name} ${slot.date} ${slot.hour} ${slot.court}`;}
export function filterSlots(slots,venue,scope) {const courts=allowedCourts(venue,scope);return slots.filter(s=>courts.includes(Number(String(s.court).replace(/^场地/,""))));}
export function autoOrderCandidate(slots,config,halted,attempts,now=Date.now()) {
  if(!config.autoOrder||halted||slots.length!==1) return null;
  const slot=slots[0];return now-(attempts[slotKey(slot)]??-Infinity)>=bookingRules.autoOrderRetryCooldownSeconds*1000?slot:null;
}
export function taskExpired(task,now=Date.now()) {return task.mode==="rush"&&now>=task.config.deadline;}
