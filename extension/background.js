import {Controller} from "./controller.js";
const controller=new Controller(chrome);
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(message.target==="audio"||message.type==="STATE_CHANGED") return;
  if(sender.id!==chrome.runtime.id) return;
  controller.handle(message,sender).then(data=>respond({ok:true,data})).catch(error=>respond({ok:false,error:error.message}));
  return true;
});
chrome.alarms.onAlarm.addListener(alarm=>controller.onAlarm(alarm.name).catch(console.error));
chrome.tabs.onRemoved.addListener(tabId=>controller.removed(tabId).catch(console.error));
chrome.runtime.onInstalled.addListener(()=>{
  chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(console.error);
  controller.init().catch(console.error);
});
chrome.runtime.onStartup.addListener(()=>{
  chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(console.error);
  controller.init().catch(console.error);
});
controller.init().catch(console.error);
