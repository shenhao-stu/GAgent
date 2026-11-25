// A deterministic backend-ready clock isolates bridge scheduling from network latency.
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const {extract}=require('./webui_source.cjs');
const source=fs.readFileSync('app/src/main/assets/ga_runtime/webui/pclink.js','utf8');
function pipeline(ios,ready=10,steps=3,cancel=false){
  let now=0,id=0,resultAt=null,polls=0;const timers=[],jobs={};
  const ctx={IS_IOS:ios,Date:{now:()=>now},JSON,Math,
    setTimeout:(fn,ms)=>timers.push({fn,at:now+ms}),GA:{send(cmd){
      if(!cmd.startsWith('/jobresult')){const job=String(++id);jobs[job]=now+ready;return JSON.stringify({job})}
      polls++;const job=cmd.split(' ')[1];return JSON.stringify(now<jobs[job]?{pending:true}:{result:'{"ok":1}'})
    }}};
  vm.createContext(ctx);vm.runInContext(extract(source,'call'),ctx);
  const next=()=>ctx.call('read',r=>{if(!r.ok||--steps===0)resultAt=now;else next()},0,()=>!cancel||now<20);
  next();
  while(timers.length){timers.sort((a,b)=>a.at-b.at);const t=timers.shift();now=t.at;t.fn();if(now>50000)throw Error('Unbounded polling')}
  return {completedAt:resultAt,polls};
}
assert.deepEqual(pipeline(false),{completedAt:900,polls:3});
assert.deepEqual(pipeline(true),{completedAt:120,polls:3});
for(const ready of [100,180,300,500,1000,1500,5000])assert(pipeline(true,ready,1).completedAt<=pipeline(false,ready,1).completedAt,'Fast probes must preserve the original slow-response schedule');
assert.deepEqual(pipeline(true,10,1,true),{completedAt:null,polls:0});
const timeout=pipeline(true,Infinity,1);assert(timeout.completedAt>=48000&&timeout.completedAt<48500);
const ctx={IS_IOS:true,connected:true,knownNames:new Set(['selected']),timer:null,tok:0,lastPs:[],
  setPeer:()=>{},rememberPeer:()=>{},setHeroMode:()=>{},renderSide:()=>{},clearTimeout:()=>{},isHistoryPeer:()=>false,
  poll:()=>{throw Error('A known selection must not wait for every peer')},arm:()=>{},pullMsgs:(done,depth,alive)=>{assert(alive());done()}};
vm.createContext(ctx);vm.runInContext(extract(source,'selPeer'),ctx);ctx.selPeer('selected');
console.log(JSON.stringify({fixture:'three serial jobs, each backend ready in 10 ms',previousFixedPollingMs:900,iosAdaptivePollingMs:120,networkExcluded:true,cancellation:true,deadlineMs:timeout.completedAt,knownSelectionSkipsPeerEnumeration:true}));

// Reading native account state once per sort keeps the bridge cost independent of list size.
let reads=0;const sortContext={peerMeta:()=>{reads++;return {p0:{pin:true}}},baseOf:n=>n,noHub:n=>n,isNew:p=>p.name==='d.new'};
vm.createContext(sortContext);vm.runInContext(['metaOf','orderPeers'].map(n=>extract(source,n)).join('\n'),sortContext);
const peers=Array.from({length:200},(_,i)=>({name:'p'+i,ts:i}));peers.push({name:'d.new',ts:0});
sortContext.orderPeers(peers);assert.equal(reads,1);assert.equal(peers[0].name,'d.new');assert.equal(peers[1].name,'p0');assert.equal(peers[2].name,'p199');
const selection={IS_IOS:true,curPeer:null,isNew:()=>false,lastPeerSaved:()=>({}),hasPid:()=>false};
vm.createContext(selection);vm.runInContext(source.match(/const isAgent=[^;]+;/)[0]+'\n'+extract(source,'pickPeer'),selection);
const history={name:'history.fixture',caps:['history-v1']},live={name:'live.fixture',caps:['get','put']};
assert.equal(selection.pickPeer([history]),null,'Removed history providers must not become a conversation');
assert.equal(selection.pickPeer([history,live]),live.name);
console.log('PASS: 200-row sort reads account metadata once; selection only accepts readable conversations.');
