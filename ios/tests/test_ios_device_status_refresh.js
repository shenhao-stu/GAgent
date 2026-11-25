// The existing poll loop updates visible cards; it must not create another timer or flood the bridge.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app/src/main/assets/ga_runtime/webui/ios_ui.js','utf8');
const part=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
let now=10000,ios=true,visible=true,inert=false,calls=0;
let state={ok:true,connected:true,consent:true,hid_ready:true,capture_source:'replaykit',screen_sharing_active:false,mirroring:false,calibrated:true,ready:false};
const card={textContent:'',dataset:{},getClientRects:()=>visible?[{}]:[],closest:()=>inert?{}:null};
const context={Date:{now:()=>now},document:{hidden:false,querySelectorAll:()=>[card]},isIOSClient:()=>ios,t:key=>key,
  GA:{boardStatus(){calls++;return JSON.stringify(state)}},setInterval(){throw Error('No new timer is permitted')}};
vm.createContext(context);vm.runInContext(part('function iosBoardPresentation(','function initIOSNavigation('),context);
context.refreshIOSDeviceStatus(false);assert.equal(calls,1);assert.equal(card.textContent,'iosPhoneShare');
state={...state,screen_sharing_active:true,ready:true};
for(const delta of [100,700,1500,1999]){now=10000+delta;context.refreshIOSDeviceStatus(false)}
assert.equal(calls,1);assert.equal(card.textContent,'iosPhoneShare');
now=12000;context.refreshIOSDeviceStatus(false);assert.equal(calls,2);assert.equal(card.textContent,'iosPhoneReady');
state={...state,calibrated:false};inert=true;now+=3000;context.refreshIOSDeviceStatus(false);assert.equal(calls,2);
inert=false;visible=false;context.refreshIOSDeviceStatus(false);assert.equal(calls,2);
visible=true;context.document.hidden=true;context.refreshIOSDeviceStatus(false);assert.equal(calls,2);
context.document.hidden=false;context.refreshIOSDeviceStatus(false);assert.equal(calls,3);assert.equal(card.textContent,'iosPhoneCalibrate');
state={...state,connected:false};context.refreshIOSDeviceStatus();assert.equal(calls,4);assert.equal(card.textContent,'iosPhoneConnect');
ios=false;now+=3000;context.refreshIOSDeviceStatus();context.refreshIOSDeviceStatus(false);assert.equal(calls,4);
console.log('PASS: visible device status refreshes within the existing poll cadence, throttles bridge calls, skips hidden/covered cards and Android, and supports explicit navigation refresh.');
