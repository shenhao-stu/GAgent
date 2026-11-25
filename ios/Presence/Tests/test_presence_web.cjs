// The handoff strip and the settings rows against a minimal page: what each state draws, what each button and
// switch asks for, and that nothing the chat already shows is drawn again.
//   node ios/Presence/Tests/test_presence_web.cjs
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const here=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(here,'Web/presence.js'),'utf8');
// Messages are built inside the page's realm; compare them by value.
const same=(actual,expected)=>assert.equal(JSON.stringify(actual),JSON.stringify(expected));

function element(tag){
  const classes=new Set();
  const node={tag,children:[],parent:null,dataset:{},attributes:{},hidden:false,disabled:false,onclick:null,_html:'',_text:'',
    get className(){return [...classes].join(' ')},set className(v){classes.clear();String(v).split(' ').filter(Boolean).forEach(c=>classes.add(c))},
    classList:{toggle(name,on){on?classes.add(name):classes.delete(name)},contains:name=>classes.has(name)},
    append(...kids){kids.forEach(kid=>{kid.parent=node});node.children.push(...kids)},appendChild(kid){kid.parent=node;node.children.push(kid);return kid},
    insertBefore(kid,before){const at=node.children.indexOf(before);kid.parent=node;node.children.splice(at<0?node.children.length:at,0,kid);return kid},
    after(...kids){const list=node.parent.children;kids.forEach(kid=>{kid.parent=node.parent});list.splice(list.indexOf(node)+1,0,...kids)},
    closest(selector){let at=node;while(at&&!at.classList.contains(selector.slice(1)))at=at.parent;return at},
    setAttribute(name,value){node.attributes[name]=String(value)},getAttribute(name){return name in node.attributes?node.attributes[name]:null},
    get firstChild(){return node.children[0]||null},
    get innerHTML(){return node._html},set innerHTML(v){node._html=v;node.children=[];node._text=''},
    get textContent(){return node._text+node.children.map(c=>c.textContent).join('')},set textContent(v){node._text=String(v);node.children=[]}};
  return node;
}
const words={zh:{gaPresenceLive:'灵动岛与锁屏显示进度',gaPresenceLock:'锁屏显示步骤内容'},
  en:{gaPresenceLive:'Progress on Dynamic Island',gaPresenceLock:'Step details on Lock Screen'}};
function page({convo='a',withComposer=true,withSettings=true,lang='zh',busy=false}={}){
  const comp=element('div'),cap=element('div');comp.append(cap);
  // The page's general settings card: the sound row, then another row.
  const card=element('div'),soundRow=element('div'),sound=element('button'),nextRow=element('div');
  soundRow.className='row';soundRow.append(sound);card.append(soundRow,nextRow);
  const found={comp:withComposer&&comp,swSound:withSettings&&sound};
  const head=element('head'),root=element('html'),posted=[],ready=[],stops=[],sent=[],timers=[];
  const away=[];let clock=Date.now();
  const context={window:null,curConvo:convo&&{id:convo},stopRunClean:()=>stops.push(1),startTask:text=>{sent.push(text);return !busy},notifyAway:(level,c)=>away.push(level+':'+(c?c.id:'')),
    I18N:{zh:{},en:{}},t:key=>context.I18N[lang][key],setInterval:fn=>timers.push(fn),Date:{now:()=>clock},crypto:require("node:crypto"),
    document:{head,documentElement:root,createElement:element,getElementById:id=>found[id]||null},
    webkit:{messageHandlers:{gaPresence:{postMessage:m=>(m.ready?ready:posted).push(m)}}}};
  context.window=context;context.__gaPresence={css:'#gaPresence{}',words};
  vm.createContext(context);vm.runInContext(source,context);
  const bar=comp.children[0];
  return {context,comp,cap,card,soundRow,nextRow,head,posted,ready,stops,sent,away,bar,tick:()=>timers.forEach(fn=>fn()),advance:ms=>clock+=ms,
    standsIn:()=>root.classList.contains('gpHandoff'),text:()=>bar.children[1].textContent,primary:()=>bar.children[2],end:()=>bar.children[3]};
}
const labels={takeOver:'我来操作',handBack:'交还给 GAgent',handingBack:'正在交还…',end:'结束',released:'键鼠已松开'};
const state=(phase,extra={})=>({cid:'a',phase,running:['thinking','looking','acting','working'].includes(phase),
  status:{acting:'正在操作',asking:'需要你回答',paused:'你在操作',done:'已完成',failed:'没有完成'}[phase]||phase,
  now:'点击「去结算」',labels,...extra});

// Added once, as the composer's first child, hidden until there is a task.
let p=page();
assert.equal(p.comp.children.length,2);assert.equal(p.comp.children[1],p.cap,'the composer itself is untouched');
assert.equal(p.bar.id,'gaPresence');assert.equal(p.bar.hidden,true);
assert.equal(p.head.children[0].textContent,'#gaPresence{}');
vm.runInContext(source,p.context);assert.equal(p.comp.children.length,2,'loading twice adds one strip');
assert.equal(page({withComposer:false}).context.GAPresence,undefined,'a page without a composer is left alone');

// Opening a card for another conversation selects that conversation without sending a turn or taking over.
p=page({convo:'b'});
p.context.convos=[{id:'a'},{id:'b'}];
p.context.openConvo=c=>{p.context.curConvo=c};
const destinations=[];p.context.GAIOS={navigate:where=>destinations.push(where)};
assert.equal(p.context.GAPresence.openConversation('a'),true);
assert.equal(p.context.curConvo.id,'a');
same(destinations,['assistant']);
assert.equal(p.context.GAPresence.openConversation('missing'),false);
assert.equal(p.context.curConvo.id,'a');
assert.equal(p.sent.length,0);assert.equal(p.posted.length,0);
p=page();

// The agent works in the open conversation: its action in its own words, and the way to take the phone over.
// No step count and no stop button: the chat's header and composer have both. The page's own live line gives
// way for as long as the strip stands there.
p.context.GAPresence.render(state('acting'));
assert.equal(p.bar.hidden,false);assert.equal(p.bar.dataset.phase,'acting');assert.equal(p.standsIn(),true);
assert.equal(p.text(),'点击「去结算」');
assert.equal(p.primary().textContent,'我来操作');assert.equal(p.end().hidden,true,'the composer stops its own run');
p.primary().onclick();
same(p.posted,[{command:'pause',cid:'a'}]);assert.equal(p.stops.length,0,'the run is the engine\'s to pause first');

// The user has the phone: hand back or end, both worded. The engine has taken the phone from the run this page
// shows, so the page closes its own view of that run now, as its own Pause does, once.
p.context.GAPresence.render(state('paused'));assert.equal(p.stops.length,1);
p.context.GAPresence.render(state('paused'));assert.equal(p.stops.length,1,'once per handoff');
assert.equal(p.text(),'你在操作 · GAgent 键鼠已松开');assert.equal(p.standsIn(),true);
assert.equal(p.primary().textContent,'交还给 GAgent');assert.equal(p.end().textContent,'结束');
p.end().onclick();same(p.posted[1],{command:'stop',cid:'a'});assert.equal(p.stops.length,1,'nothing is running to close');
p.primary().onclick();same(p.posted[2],{command:'resume',cid:'a',request:p.posted[2].request});assert.ok(p.posted[2].request);
// The engine takes the phone back only when the paused turn has ended: until then the button says so and is inert.
assert.equal(p.primary().textContent,'正在交还…');assert.equal(p.primary().disabled,true);
p.context.GAPresence.render(state('paused'));assert.equal(p.primary().disabled,true,'the next reading is still the handoff');
// The phone handed back, the turn that goes on is the page's to send: it draws it, as it does its own Resume's.
// The handoff still showing meanwhile does not close the run that turn started.
assert.equal(p.context.GAPresence.handBack('a','请继续',p.posted[2].request),true);same(p.sent,['请继续']);
p.context.GAPresence.render(state('paused'));assert.equal(p.stops.length,1);
p.context.GAPresence.render(state('thinking'));assert.equal(p.primary().disabled,false);assert.equal(p.primary().textContent,'我来操作');
p.context.GAPresence.render(state('paused'));assert.equal(p.primary().textContent,'交还给 GAgent','a later handoff starts afresh');
assert.equal(p.stops.length,2);

// Ending a pending hand-back must leave the next handoff usable immediately.
{
  const ended=page();ended.context.GAPresence.render(state('paused'));
  ended.primary().onclick();ended.end().onclick();
  same(ended.posted,[{command:'resume',cid:'a',request:ended.posted[0].request},{command:'stop',cid:'a'}]);
  ended.context.GAPresence.render(state('stopped'));assert.equal(ended.bar.hidden,true);
  ended.context.GAPresence.render(state('paused'));
  assert.equal(ended.primary().disabled,false,'ended hand-back must not disable a new handoff');
  assert.equal(ended.primary().textContent,'交还给 GAgent');
}

// Everything else the open chat shows by itself: its question with the choices, its outcome. Nothing is drawn twice.
{
  const delayed=page();delayed.context.GAPresence.render(state('paused'));
  delayed.primary().onclick();const old=delayed.posted.at(-1).request;
  delayed.end().onclick();
  assert.equal(delayed.context.GAPresence.handBack('a','请继续',old),false,'a callback after End cannot start a task');
  assert.equal(delayed.sent.length,0);
  delayed.primary().onclick();const fresh=delayed.posted.at(-1).request;
  assert.notEqual(fresh,old);
  assert.equal(delayed.context.GAPresence.handBack('a','请继续',old),false,'the old callback cannot consume a new request');
  assert.equal(delayed.context.GAPresence.handBack('a','请继续',fresh),true);
  assert.equal(delayed.context.GAPresence.handBack('a','请继续',fresh),false,'one request sends only once');
  same(delayed.sent,['请继续']);
}
{
  const expired=page();expired.context.GAPresence.render(state('paused'));expired.primary().onclick();
  expired.advance(90001);expired.tick();
  assert.equal(expired.primary().disabled,false,'an unchanged snapshot must not leave the hand-back button disabled forever');
}
for(const phase of ['asking','done','failed','stopped']){
  p.context.GAPresence.render(state(phase));assert.equal(p.bar.hidden,true,phase);assert.equal(p.standsIn(),false,phase);
}
p.context.GAPresence.render(null);assert.equal(p.bar.hidden,true);assert.equal(p.standsIn(),false);

// The strip is the open conversation's. A task in another one is that conversation's to show, and the page's
// own controls stay; opening it brings the strip without waiting for the task to change.
p=page({convo:'b'});p.context.GAPresence.render(state('acting'));
assert.equal(p.bar.hidden,true);assert.equal(p.standsIn(),false);
p.context.curConvo={id:'a'};p.tick();assert.equal(p.bar.hidden,false);assert.equal(p.standsIn(),true);
p.context.curConvo={id:'b'};p.tick();assert.equal(p.bar.hidden,true);assert.equal(p.standsIn(),false);
// A handoff in another conversation leaves the open one's run alone, until that conversation is opened.
p.context.GAPresence.render(state('paused'));assert.equal(p.stops.length,0);
p.context.curConvo={id:'a'};p.tick();assert.equal(p.stops.length,1);
// Nor does the page claim a turn it could not send, or one for another conversation: the caller sends it.
p.context.curConvo={id:'b'};assert.equal(p.context.GAPresence.handBack('a','请继续'),null);assert.equal(p.sent.length,0);
p=page({busy:true});p.context.GAPresence.render(state('paused'));p.primary().onclick();assert.equal(p.context.GAPresence.handBack('a','请继续',p.posted[0].request),false);same(p.sent,['请继续']);

// One announcement per event: the page's away-notification is silenced only for the task Presence follows.
p=page();p.context.notifyAway('done',{id:'a'});same(p.away,['done:a']);           // nothing followed: untouched
p.context.GAPresence.render(state('acting'));
p.context.notifyAway('ask',{id:'a'});p.context.notifyAway('done');same(p.away,['done:a']);   // followed, also when the page means the open chat
p.context.notifyAway('done',{id:'b'});same(p.away,['done:a','done:b']);           // another conversation still notifies
p.context.GAPresence.render(null);p.context.notifyAway('done',{id:'a'});assert.equal(p.away.length,3);

// The two switches: rows of the page's settings card, right after the sound row, labelled from the page's word table.
p=page({lang:'en'});
same(p.ready,[{ready:true}]);
assert.equal(p.card.children.length,4);assert.equal(p.card.children[0],p.soundRow);assert.equal(p.card.children[3],p.nextRow);
const [live,lock]=[p.card.children[1],p.card.children[2]].map(row=>({row,label:row.children[1],sw:row.children[2].children[0]}));
assert.equal(live.label.textContent,'Progress on Dynamic Island');assert.equal(lock.sw.attributes['aria-label'],'Step details on Lock Screen');
assert.equal(live.label.dataset.i18n,'gaPresenceLive');assert.equal(lock.sw.dataset.i18nAria,'gaPresenceLock');
assert.equal(p.context.I18N.zh.gaPresenceLock,'锁屏显示步骤内容','the page\'s language switch finds both languages');
assert.equal(live.sw.attributes.role,'switch');assert.ok(live.row.classList.contains('row'));
assert.ok(live.row.hidden&&lock.row.hidden,'no row before the native side says there is an island to govern');
// Values come from the native side; a tap flips the switch at once and reports it.
p.context.GAPresence.configure({live:true,lockDetail:false});
assert.equal(live.sw.attributes['aria-checked'],'true');assert.ok(live.sw.classList.contains('on'));
assert.ok(!live.row.hidden&&!lock.row.hidden);
assert.equal(lock.sw.attributes['aria-checked'],'false');assert.equal(lock.sw.disabled,false);
lock.sw.onclick();same(p.posted,[{setting:'lockDetail',value:true}]);assert.equal(lock.sw.attributes['aria-checked'],'true');
// Without the live activity there is no Lock Screen card: the second switch keeps its value and is set aside.
live.sw.onclick();same(p.posted[1],{setting:'live',value:false});
assert.equal(lock.sw.disabled,true);assert.ok(lock.row.classList.contains('gpOff'));assert.equal(lock.sw.attributes['aria-checked'],'true');
live.sw.onclick();assert.equal(lock.sw.disabled,false);assert.ok(!lock.row.classList.contains('gpOff'));
vm.runInContext(source,p.context);assert.equal(p.card.children.length,4,'loading twice adds the rows once');
// A page without that settings card still gets the strip, and values for absent switches are ignored.
p=page({withSettings:false});assert.equal(p.card.children.length,2);p.context.GAPresence.configure({live:false,lockDetail:false});
assert.equal(p.bar.id,'gaPresence');same(p.ready,[{ready:true}]);

// Copy comes from the native surface, including the turn sent on handback.
const copy=fs.readFileSync(path.join(here,'Core/PresenceCopy.swift'),'utf8');
for(const set of Object.values(words))for(const word of Object.values(set))assert.ok(copy.includes('"'+word+'"'),'PresenceCopy.settings: '+word);
for(const prompt of ['我已完成接管，请从当前状态继续原任务，保留已完成的结果。',
  'I have finished taking over. Continue the original task from the current state, preserving completed work.']){
  assert.ok(copy.includes(prompt),'PresenceCopy.resumePrompt');
}
console.log('PASS: the strip is added once and hidden when idle; it draws only the open conversation\'s handoff, stands in for the page\'s own live line while it does, and repeats nothing the chat shows; commands carry the task\'s conversation; a hand-back is kept pending; the page\'s own notification is silenced only for the followed task; the two settings rows are added once, labelled in the page\'s language, and report each change; handback copy is supplied by the native surface.');
