/* GAgent Presence in the chat page: the handoff strip above the composer, and its own two switches on the
   settings page. Added to the loaded page by ios/Presence/App/WebSurface.swift, which also supplies every word.
   What it knows of the page is listed here and nowhere else: #comp and #swSound (where it adds its rows),
   curConvo (which conversation is open), stopRunClean and startTask (the page's own stop and send),
   convos/openConvo and GAIOS.navigate/closeSheets (card navigation),
   notifyAway (its away notice), I18N and t (the word table), and by name in its style sheet #twLive (the
   live line it stands in for). Buttons and switches go to the native side, the same path as the island. */
(function(){
  'use strict';
  const comp=document.getElementById('comp'),setup=window.__gaPresence||{};
  if(window.GAPresence||!comp)return;
  const style=document.createElement('style');style.textContent=setup.css||'';document.head.appendChild(style);
  const post=message=>{try{webkit.messageHandlers.gaPresence.postMessage(message)}catch(e){}};
  const svg=d=>'<svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">'+d+'</svg>';
  const GLYPH={
    thinking:svg('<path d="M11 2.5l2.1 6.4 6.4 2.1-6.4 2.1L11 19.5l-2.1-6.4L2.5 11l6.4-2.1z"/>'),
    looking:svg('<path fill-rule="evenodd" d="M12 5c6.2 0 9.8 7 9.8 7s-3.6 7-9.8 7-9.8-7-9.8-7S5.8 5 12 5zm0 3.4a3.6 3.6 0 1 0 0 7.2 3.6 3.6 0 0 0 0-7.2z"/>'),
    acting:svg('<path d="M5.2 2.8l14.6 8.3-6.3 1.7 3.7 6.6-3 1.7-3.7-6.6-4.7 4.4z"/>'),
    working:svg('<path fill-rule="evenodd" d="M10.3 2.5h3.4l.5 2.6 1.5.9 2.5-.9 1.7 3-2 1.7v1.8l2 1.7-1.7 3-2.5-.9-1.5.9-.5 2.6h-3.4l-.5-2.6-1.5-.9-2.5.9-1.7-3 2-1.7v-1.8l-2-1.7 1.7-3 2.5.9 1.5-.9zM12 8.8a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 0 0 0-6.4z"/>'),
    paused:svg('<rect x="5.5" y="4.5" width="4.6" height="15" rx="1.5"/><rect x="13.9" y="4.5" width="4.6" height="15" rx="1.5"/>'),
    end:svg('<rect x="5" y="5" width="14" height="14" rx="3.2"/>'),
    play:svg('<path d="M7 4.6v14.8c0 .8.9 1.3 1.6.8l11.2-7.4a1 1 0 0 0 0-1.6L8.6 3.8C7.9 3.3 7 3.8 7 4.6z"/>')
  };
  const make=(tag,name)=>{const node=document.createElement(tag);if(name)node.className=name;return node};
  const bar=make('div'),glyph=make('span','gpGlyph'),text=make('div','gpText'),strong=make('b'),rest=make('span');
  const primary=make('button'),end=make('button','gpEnd');
  bar.id='gaPresence';bar.hidden=true;bar.setAttribute('role','status');primary.type=end.type='button';
  text.append(strong,rest);bar.append(glyph,text,primary,end);comp.insertBefore(bar,comp.firstChild);
  let shown=null,open=false;   // the task last given, and whether it was the open conversation's when drawn
  let handedOver=false;        // the open conversation's handoff card is drawn
  let returning=null;          // the handoff being handed back, until the engine has taken it
  const own=state=>{try{return !!state&&!!curConvo&&String(curConvo.id)===String(state.cid)}catch(e){return false}};
  function send(command){
    // The engine takes the phone back only once the paused turn has ended, which can take a while: say so.
    if(command==='resume'){returning={cid:shown.cid,request:crypto.randomUUID(),until:Date.now()+90000};render(shown)}
    if(command==='stop')returning=null;
    post({command:command,cid:shown.cid,...(command==='resume'?{request:returning.request}:{})});
  }
  function button(node,command,icon,label){
    node.hidden=!command;if(!command)return;
    node.innerHTML=icon;node.setAttribute('aria-label',label);node.onclick=()=>send(command);
    const word=make('span');word.textContent=label;node.appendChild(word);
  }
  // The strip belongs to the conversation that is open and says nothing the chat already says: the page shows
  // its own question, outcome, step count, a stop button and, in #twLive, the tool at work. What the page has
  // no place for is the handoff. While the agent works: its action in its own words, and the way to take the
  // phone over. While the user has the phone: the way to hand it back, or to end. For as long as the strip
  // offers these it stands in for the page's live line (the gpHandoff class).
  function render(state){
    shown=state;open=own(state);
    const running=open&&state.running,paused=open&&state.phase==='paused',words=state&&state.labels||{};
    if(!state||state.phase!=='paused'||returning&&(returning.cid!==state.cid||Date.now()>returning.until))returning=null;
    // The engine has taken the phone from the run this page shows (from here, the island or the Lock Screen):
    // the page closes its own view of that run now, as its own Pause does, and not only once the engine has
    // wound the turn down, which can take as long as the model call in flight.
    if(paused&&!handedOver)try{stopRunClean()}catch(e){}
    handedOver=paused;
    document.documentElement.classList.toggle('gpHandoff',running||paused);
    bar.hidden=!(running||paused);if(bar.hidden)return;
    bar.dataset.phase=state.phase;glyph.innerHTML=GLYPH[state.phase]||GLYPH.working;
    strong.textContent=running?state.now:state.status;
    rest.textContent=running?'':' · GAgent '+words.released;
    if(running)button(primary,'pause',GLYPH.paused,words.takeOver);
    else button(primary,'resume',GLYPH.play,returning?words.handingBack:words.handBack);
    primary.disabled=!!returning;
    button(end,paused?'stop':'',GLYPH.end,words.end);
  }
  // Once the engine has the phone back, the turn that goes on is the page's to send, as its own Resume does:
  // it draws that turn, and it no longer takes the new run for the one it closed. Answers whether it did;
  // if not, the native side sends the turn itself.
  function handBack(cid,text,request){
    if(!own({cid:cid}))return null;
    if(!returning||returning.cid!==cid||returning.request!==request)return false;
    returning=null;
    try{return startTask(text)===true}catch(e){return false}
  }
  function openConversation(cid){
    try{
      const convo=convos.find(c=>String(c.id)===String(cid));if(!convo)return false;
      if(window.GAIOS)GAIOS.navigate('assistant');
      if(typeof closeSheets==='function')closeSheets();
      openConvo(convo);return own({cid:cid});
    }catch(e){return false} // the chat may still be loading; the native side retains the request
  }
  // Which conversation is open changes without the task changing.
  setInterval(()=>{if(shown&&(open!==own(shown)||returning&&Date.now()>returning.until))render(shown)},500);
  // Presence alone announces the question and the outcome of the task it follows (island or notification);
  // the page's own away-notification for that conversation would ring a second time.
  const away=window.notifyAway;
  if(typeof away==='function')window.notifyAway=function(level,convo){
    let about=convo;try{about=about||curConvo}catch(e){}
    if(shown&&about&&String(about.id)===String(shown.cid))return;
    return away.apply(this,arguments);
  };
  // The two switches, as rows of the page's general settings. Their labels are entries of the page's own word
  // table, so its language switch covers them. The values live on the native side: a row shows once it has one.
  const line=d=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+d+'</svg>';
  const switches={},words=setup.words||{};
  function setting(name,key,tint,icon){
    const row=make('div','row gpSetting'),tile=make('span','rowIco '+tint),label=make('span','k'),value=make('span','v'),sw=make('button','sw');
    tile.innerHTML=icon;tile.setAttribute('aria-hidden','true');
    label.dataset.i18n=sw.dataset.i18nAria=key;
    let word=(words.zh||{})[key]||'';try{word=t(key)}catch(e){}
    label.textContent=word;sw.setAttribute('aria-label',word);
    sw.type='button';sw.setAttribute('role','switch');row.hidden=true;
    sw.onclick=()=>{const on=sw.getAttribute('aria-checked')!=='true';configure({[name]:on});post({setting:name,value:on})};
    value.appendChild(sw);row.append(tile,label,value);switches[name]={row:row,sw:sw};return row;
  }
  function configure(values){
    for(const name in switches)if(name in values){
      const sw=switches[name].sw,on=!!values[name];sw.classList.toggle('on',on);sw.setAttribute('aria-checked',String(on));
      switches[name].row.hidden=false;
    }
    if(!switches.live)return;
    // The Lock Screen card is part of the live activity: without one there is nothing for the second switch to set.
    const off=switches.live.sw.getAttribute('aria-checked')!=='true';
    switches.lockDetail.sw.disabled=off;switches.lockDetail.row.classList.toggle('gpOff',off);
  }
  const sound=document.getElementById('swSound'),anchor=sound&&sound.closest('.row');
  if(anchor){
    try{Object.assign(I18N.zh,words.zh);Object.assign(I18N.en,words.en)}catch(e){}
    anchor.after(setting('live','gaPresenceLive','ic-blue',line('<rect x="4" y="8" width="16" height="8" rx="4"/><path d="M8.5 12h.01M12 12h3.5"/>')),
      setting('lockDetail','gaPresenceLock','ic-teal',line('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>')));
  }
  window.GAPresence={render:render,configure:configure,handBack:handBack,openConversation:openConversation};
  post({ready:true});   // the native side answers with the switches' values and the task to draw, also after a reload
})();
