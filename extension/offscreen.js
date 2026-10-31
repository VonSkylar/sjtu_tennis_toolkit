const audio=document.getElementById("alarm");
chrome.runtime.onMessage.addListener((message,_sender,respond)=>{
  if(message.target!=="audio") return;
  if(message.type==="AUDIO_START") {audio.play().then(()=>respond({ok:true})).catch(e=>respond({ok:false,error:e.message}));return true;}
  if(message.type==="AUDIO_STOP") {audio.pause();audio.currentTime=0;respond({ok:true});}
});
