// iOS-only settings composition. It calls existing UI actions; it never writes model or device state.
function iosSettingsViewport(){
  const m = document.querySelector('meta[name="viewport"]');
  if(m && !/maximum-scale/.test(m.content)) m.content += ',maximum-scale=1,user-scalable=no';
}
function initIOSSettings(){
  if(!isIOSClient()||document.getElementById('iosSetvDone'))return;
  iosSettingsViewport();
  const hide = (el) => { if(el) el.style.display = 'none'; };
  const byI18n = (v) => document.querySelector('[data-i18n="' + v + '"]');
  ['browser','float'].forEach(k => { const s = byI18n(k); hide(s && s.closest('.menuItem')); });
  hide(document.getElementById('a11yStat'));
  hide(document.getElementById('gearDot'));
  const update = document.getElementById('rowCheckUpdate');
  if(update){
    const version = document.createElement('div');
    version.id = 'iosAppVersion'; version.className = 'row';
    let value = {};
    try{ value = JSON.parse(window.GA.appVersion() || '{}'); }catch(e){}
    const label = document.createElement('span'); label.className = 'k'; label.textContent = 'GAgent iOS';
    const detail = document.createElement('span'); detail.className = 'v';
    detail.textContent = 'v' + (value.name || '—') + ' · ' + (value.code || '—');
    const icon=document.createElement('span');icon.className='rowIco gaLogo iosBrandIcon';icon.setAttribute('aria-hidden','true');icon.textContent='GA';
    version.append(icon,label,detail); update.replaceWith(version);
  }
  const home = document.getElementById('homePanel');
  if(home && !document.getElementById('iosBoardSetup')){
    const section=document.createElement('section');section.id='iosConnections';
    section.innerHTML='<div class="secLbl"><span data-i18n="iosConnections">设备与连接</span></div><div class="card icoCard" id="iosConnectionCard"></div>';
    const entry=document.createElement('button');entry.id='iosBoardSetup';entry.type='button';entry.className='row rowBtn';
    entry.innerHTML='<span class="rowIco ic-blue" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4M11 18h2"/></svg></span><span class="iosSettingCopy"><span class="k" data-i18n="iosPhone">iPhone 操作</span></span><span class="v"><span data-ios-board-state>查看连接</span><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></span>';
    entry.onclick=()=>window.GA.boardSetup();
    section.querySelector('.card').appendChild(entry);
    home.prepend(section);
    const pc=document.getElementById('pcLinkRow');if(pc){section.querySelector('.card').appendChild(pc);document.getElementById('pcLinkSec')?.remove();}
    window.GAIOS?.refresh();
  }
  ['updatePanel','a11yPersistPanel','ganetHomeSec','ganetPanel','ganetSetupPanel','ganetDevicePanel'].forEach(id=>document.getElementById(id)?.remove());
  const detCard=document.getElementById('localDetectorRow')?.closest('.card');
  if(detCard){const lbl=detCard.previousElementSibling;if(lbl&&lbl.classList.contains('secLbl'))lbl.remove();detCard.remove();}
  byI18n('proxyHint')?.remove();
  // Android-only settings rows
  hide(document.getElementById('swFloatAlways')?.closest('.row'));
  hide(document.getElementById('a11yRow'));
  hide(document.getElementById('adbRow'));
  const op = document.getElementById('opacityRange'); hide(op && op.closest('.row'));
  hide(document.getElementById('btnClearUpd'));
  iosGroupSettingsConnections();
  iosConfigureSettingsChrome();
}

function iosConfigureSettingsChrome(){
  const settings=$('setv'),bar=settings.querySelector('.setbar'),body=settings.querySelector('.setbody'),models=$('modelv');
  settings.before(Object.assign(document.createElement('div'),{id:'iosSheetDim'}));
  const done=document.createElement('button');done.type='button';done.id='iosSetvDone';done.className='iosBarDone';
  done.textContent=t('iosDone');done.dataset.i18n='iosDone';done.onclick=closeSettings;
  const trailing=document.createElement('div');trailing.className='iosBarTrailing';trailing.append($('setvTest'),done);bar.append(trailing);
  const barHeight=()=>settings.style.setProperty('--ios-setbar-h',bar.offsetHeight+'px');
  if(window.ResizeObserver)new ResizeObserver(barHeight).observe(bar);barHeight();
  body.addEventListener('scroll',()=>{if(!settings._iosNav)settings.classList.toggle('iosScrolled',body.scrollTop>1)},{passive:true});
  iosBindSheetDrag(settings,bar,closeSettings,()=>setStack.length<=1);
  iosBindPageDrag(settings,bar,{
    can:()=>setStack.length>1&&!models.classList.contains('on'),
    begin(){const under=setStack[setStack.length-2],upper=$(settings.dataset.panel),lower=$(under.panel);
      if(!upper||!lower||upper===lower)return null;
      iosPrepareModal();const nav=iosSettingsTransition(settings,upper,lower,body.scrollTop,under.scrollTop||0);nav.gesture=true;nav.set(1);return nav},
    commit:setvBack});
  iosBindPageDrag(models,models.querySelector('.setbar'),{
    can:()=>true,begin(){const nav=iosModelNav();nav.gesture=true;nav.set(1);return nav},commit:closeModelListPage});
  models.querySelector('.setbar>.iconbtn').innerHTML=iosSettingsBackIcon();
  const failover=$('failoverSheet'),back=failover.querySelector('.foBack');
  back.innerHTML=iosSettingsBackIcon();
  const finish=done.cloneNode(true);finish.id='iosFailoverDone';finish.onclick=closeSheets;
  const actions=document.createElement('div');actions.className='iosBarTrailing';actions.append(finish);
  failover.querySelector('.foHd').append(actions);
  iosConfigureFailover();
  Object.assign(I18N.zh,{iosConnTesting:'测试中…',iosConnOk:'连接正常',iosConnFailed:'连接失败'});
  Object.assign(I18N.en,{iosConnTesting:'Testing…',iosConnOk:'Connected',iosConnFailed:'Failed'});
  const test=$('setvTest');test.className='iosConnectionTest';test.type='button';
  const label=document.createElement('span');label.dataset.i18n='testConn';label.textContent=t('testConn');
  test.removeAttribute('aria-label');test.removeAttribute('data-i18n-aria');
  test.append(label);test.setAttribute('aria-live','polite');$('provSaveBar').prepend(test);
  const remove=$('provDelBtn');remove.removeAttribute('data-i18n');remove.dataset.i18nAria='del';remove.setAttribute('aria-label',t('del'));
  remove.innerHTML='<span class="iosDeleteIcon">'+ICO_TRASH+'</span>';
}

const IOS_CONNECTION={idle:['testConn','<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>'],testing:['iosConnTesting',''],
  ok:['iosConnOk','<path d="M20 6 9 17l-5-5"/>'],failed:['iosConnFailed','<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>']};
const IOS_CONNECTION_HOLD={ok:2600,failed:5000};
let iosConnectionTimer=0;
function iosConnectionState(state){
  const button=$('setvTest'),label=button.querySelector('span'),[key,icon]=IOS_CONNECTION[state];
  if(!label)return;
  clearTimeout(iosConnectionTimer);
  if(state==='idle')button.style.minWidth='';else if(!button.style.minWidth)button.style.minWidth=button.offsetWidth+'px';
  button.dataset.state=state;button.setAttribute('aria-busy',state==='testing');
  label.dataset.i18n=key;label.textContent=t(key);
  if(icon)button.querySelector('svg').innerHTML=icon;
  if(IOS_CONNECTION_HOLD[state])iosConnectionTimer=setTimeout(()=>iosConnectionState('idle'),IOS_CONNECTION_HOLD[state]);
}
function iosConnectionReason(error){
  const text=String(error||'').replace(/<[^<>]* object at 0x[0-9a-f]+>[:,]? */g,'').replace(/\s+/g,' ').trim();
  const kind=/^(\w+): /.exec(text),cause=/\(Caused by [^'"]*(['"])(.+?)(?:\1\)|$)/.exec(text);
  if(kind&&cause)return kind[1]+': '+cause[2].replace(/ \([^)]*$/,'');
  const status=(/^HTTP \d{3}/.exec(text)||[''])[0],said=/['"]message['"]: ?(['"])(.+?)\1 ?[,}]/.exec(text);
  if(said)return (status+' '+said[2]).trim();
  if(status&&/^HTTP \d{3}: ?</.test(text))return status;
  return text.length>160?text.slice(0,159)+'…':text;
}

function iosConfigureFailover(){
  const sheet=$('failoverSheet'),body=sheet.querySelector('.shBody');
  const master=$('foEnabledSw').closest('.foRow');master.removeAttribute('style');master.classList.add('iosFoMaster');
  const card=document.createElement('div');card.className='iosFoCard';master.before(card);card.append(master);
  const title=master.querySelector('.nm');title.removeAttribute('style');title.dataset.i18n='iosFoAutomatic';title.textContent=t('iosFoAutomatic');
  const state=document.createElement('div');state.id='iosFoState';state.className='sub';state.setAttribute('aria-live','polite');master.querySelector('.mid').append(state);
  const icon=document.createElement('span');icon.className='iosFoIcon';icon.setAttribute('aria-hidden','true');icon.innerHTML=AUTO_GLYPH;master.prepend(icon);
  const use=document.createElement('button');use.id='iosFoUse';use.className='iosFoUse';use.textContent=t('iosFoUse');use.dataset.i18n='iosFoUse';
  use.onclick=()=>{selectAuto({name:(foCfg&&foCfg.name)||'auto'},true);iosUpdateFailover()};card.append(use);
  const intro=sheet.querySelector('[data-i18n="failoverHint"]');intro.removeAttribute('style');intro.className='iosFoHint';intro.dataset.i18n='iosFoIntro';intro.textContent=t('iosFoIntro');card.after(intro);
  const section=body.querySelector('[data-i18n="failoverChain"]');section.removeAttribute('style');section.removeAttribute('data-i18n');section.className='iosFoSection';section.textContent='';
  const label=document.createElement('span');label.textContent=t('iosFoOrder');label.dataset.i18n='iosFoOrder';
  const edit=document.createElement('button');edit.id='iosFoEdit';edit.className='iosFoTextButton';edit.setAttribute('aria-pressed','false');
  edit.onclick=()=>{sheet.classList.toggle('iosFoEditing');iosUpdateFailover()};section.append(label,edit);
  const hint=document.createElement('p');hint.id='iosFoOrderHint';hint.className='iosFoHint';$('foChain').after(hint);
  const advanced=$('foAdv');advanced.removeAttribute('style');advanced.classList.add('iosFoCard');
  const head=advanced.querySelector('.advHead');head.setAttribute('aria-controls','iosFoRetryBody');head.setAttribute('aria-expanded','false');
  const advancedLabel=head.querySelector('span');advancedLabel.dataset.i18n='iosFoRetries';advancedLabel.textContent=t('iosFoRetries');
  const summary=document.createElement('span');summary.id='iosFoRetrySummary';head.append(summary);
  const content=advanced.querySelector('.advBody');content.id='iosFoRetryBody';
  head.onclick=()=>{advanced.classList.toggle('open');head.setAttribute('aria-expanded',String(advanced.classList.contains('open')))};
  for(const id of ['foRetries','foDelay']){
    const input=$(id);input.closest('.field').querySelector('label').htmlFor=id;
    input.addEventListener('input',iosUpdateFailover);
  }
  const restore=content.querySelector('button');restore.removeAttribute('style');restore.className='iosFoTextButton iosFoRestore';
  const note=document.createElement('p');note.className='iosFoHint';note.dataset.i18n='iosFoRetryHint';note.textContent=t('iosFoRetryHint');advanced.after(note);
}

function iosUpdateFailover(){
  if(!$('iosFoState'))return;
  const count=foChain.filter(it=>it.on).length,editing=$('failoverSheet').classList.contains('iosFoEditing');
  $('iosFoState').textContent=t(!foEnabled?'iosFoOff':isAuto()?'iosFoActive':'iosFoReady');
  $('iosFoUse').hidden=!foEnabled||isAuto();
  $('iosFoEdit').textContent=t(editing?'iosDone':'iosFoEdit');$('iosFoEdit').setAttribute('aria-pressed',String(editing));
  $('iosFoEdit').disabled=foChain.length<2;
  $('iosFoOrderHint').textContent=t(editing?'iosFoSortHint':count===1?'iosFoSingle':'iosFoOrderHint');
  $('iosFoRetrySummary').textContent=t('iosFoRetrySummary').replace('{n}',$('foRetries').value||'10').replace('{s}',$('foDelay').value||'0.5');
  let rank=0;
  [...$('foChain').children].forEach((row,i)=>{
    const it=foChain[i];if(!it||!row.querySelector('.sub'))return;
    const role=it.on?(++rank===1?t('iosFoPrimary'):t('iosFoBackup').replace('{n}',rank-1)):t('iosFoExcluded');
    row.querySelector('.sub').textContent=role+' · '+(it.label||it.name);
    row.querySelector('.sw').classList.toggle('on',it.on);row.querySelector('.sw').setAttribute('aria-checked',String(it.on));
    row.classList.toggle('off',!it.on);
  });
}

function iosDecorateFailoverRows(){
  [...$('foChain').children].forEach((row,i)=>{
    const it=foChain[i],grip=row.querySelector('.foGrip');if(!it||!grip)return;
    const name=dispModel(it.model),move=document.createElement('button');move.className='iosFoMove';move.textContent=t('moveUp');move.disabled=i===0;
    move.setAttribute('aria-label',t('moveUp')+' '+name);move.onclick=()=>iosMoveFailover(i,i-1,'.iosFoMove');
    grip.setAttribute('aria-label',t('dragSort')+' '+name);grip.onkeydown=e=>{
      if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();iosMoveFailover(i,i+(e.key==='ArrowUp'?-1:1),'.foGrip')}
    };
    row.querySelector('.sw').setAttribute('aria-label',t('enable')+' '+name);
    row.append(move,grip);
  });
  iosUpdateFailover();
}

function iosMoveFailover(from,to,focus){
  if(runLocked()||to<0||to>=foChain.length)return;
  const [item]=foChain.splice(from,1);foChain.splice(to,0,item);renderFoChain();foPersist();
  const row=$('foChain').children[to];(row.querySelector(focus+':not(:disabled)')||row.querySelector('.foGrip')).focus();
}

function iosGroupSettingsConnections(){
  const card=$('iosConnectionCard');
  const integ=document.querySelector('#homePanel [onclick="openIntegrations()"]');
  if(card&&integ){
    const oldCard=integ.closest('.card'),lbl=oldCard&&oldCard.previousElementSibling;
    card.append(integ);
    if(lbl&&lbl.classList.contains('secLbl'))lbl.remove();
    oldCard?.remove();
  }
  const proxy=document.querySelector('#homePanel [onclick="editGlobalProxy()"]');
  if(card&&proxy){
    const row=document.createElement('div');
    row.className='row';
    row.append(proxy.querySelector('.rowIco'));
    const copy=document.createElement('span');
    copy.className='iosSettingCopy';
    copy.append(proxy.querySelector('.k'));
    const status=document.createElement('span');
    status.id='iosProxyState';status.setAttribute('role','status');
    copy.append(status);row.append(copy);
    const control=document.createElement('button');
    control.id='iosProxySwitch';control.type='button';control.className='sw';
    control.setAttribute('role','switch');control.setAttribute('aria-checked','false');
    control.dataset.i18nAria='proxy';
    control.onclick=toggleIOSProxy;
    row.append(control);card.append(row);
    proxy.remove();
  }
  $('proxyDetectBtn')?.remove();
  const perProvider=$('pvProxy')?.closest('.field');
  if(perProvider)perProvider.hidden=true;
}

let iosProxyProbe=null, iosProxyNotice='';
function iosProxyAddress(){
  try{return JSON.parse(GA.send('/ios.proxy.status')||'{}').proxy||''}
  catch(e){return ''}
}
function refreshIOSProxy(){
  const control=$('iosProxySwitch');
  if(!control)return;
  const active=!!iosProxyAddress();
  const on=active||!!iosProxyProbe;
  control.classList.toggle('on',on);
  control.setAttribute('aria-checked',String(on));
  $('iosProxyState').textContent=t(iosProxyProbe?'iosProxyChecking':iosProxyNotice||(active?'iosProxyEnabled':'iosProxyDirect'));
}
function toggleIOSProxy(){
  if(iosProxyProbe||iosProxyAddress()){
    iosProxyProbe?.poll?.stop();
    iosProxyProbe=null;
    try{iosProxyNotice=GA.send('/proxy clear')==='代理已清除'?'':'iosProxySaveFailed'}
    catch(e){iosProxyNotice='iosProxySaveFailed'}
    refreshIOSProxy();
    return;
  }
  const attempt={};
  iosProxyProbe=attempt;iosProxyNotice='';
  refreshIOSProxy();
  let system={},job;
  try{system=JSON.parse(GA.networkProxy?.()||'{}')}catch(e){}
  function finish(proxy){
    if(iosProxyProbe!==attempt)return;
    iosProxyProbe=null;
    if(proxy){
      try{GA.send('/proxy '+proxy);if(iosProxyAddress()!==proxy)iosProxyNotice='iosProxySaveFailed'}
      catch(e){iosProxyNotice='iosProxySaveFailed'}
    }else iosProxyNotice=system.vpn?'iosProxyVPNOnly':'iosProxyNoConnection';
    refreshIOSProxy();
  }
  try{job=JSON.parse(GA.send('/ios.proxy.probe '+JSON.stringify({hint:system.proxy||''}))||'{}').job}catch(e){}
  if(!job){finish('');return}
  attempt.poll=jobPoll((again,stop)=>{
    if(iosProxyProbe!==attempt){stop();return}
    try{
      const reply=JSON.parse(GA.send('/jobresult '+job)||'{}');
      if(reply.pending){again();return}
      finish(JSON.parse(reply.result||'{}').proxy||'');
    }catch(e){finish('')}
    stop();
  },{interval:250,timeout:30000,onTimeout:()=>finish('')});
}
function iosSettingsBackIcon(){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>'}
function iosSettingsWillShow(view,panel,direction){
  iosPrepareModal();const nav=view._iosNav;
  if(nav&&!(nav.gesture&&direction<0&&nav.lower===$(panel)))nav.end();
  const previous=$(view.dataset.panel);
  return previous&&previous!==$(panel)?{el:previous,scroll:view.querySelector('.setbody').scrollTop}:null;
}
function iosSettingsDidShow(view,panel,leaving,direction){
  const heading=$('setvTitle'),back=view.querySelector('.setbar>.iconbtn'),body=view.querySelector('.setbody');
  const top=setStack[setStack.length-1],root=setStack.length<=1;
  view.dataset.panel=panel;back.hidden=root;back.innerHTML=iosSettingsBackIcon();
  back.setAttribute('data-i18n-aria','back');back.setAttribute('aria-label',t('back'));heading.tabIndex=-1;
  if(!view._iosNav)body.scrollTop=top?.scrollTop||0;
  if(leaving)iosSettingsPageMotion(view,leaving,$(panel),top?.scrollTop||0,direction);
  requestAnimationFrame(()=>{if(view.classList.contains('on')&&setStack[setStack.length-1]===top)heading.focus({preventScroll:true})});
}
function iosDismissSettings(){
  const models=$('modelv');models._iosNav?.end();
  if(models.classList.contains('on'))iosPresentView(models,false);
  const view=$('setv');view._iosNav?.end();view.inert=false;iosPresentView(view,false);
}

const IOS_NAV_MS=420,IOS_NAV_EASE='cubic-bezier(.32,.72,0,1)';
function iosNavFrame(p,extent){
  p=Math.min(1,Math.max(0,p));
  return {upper:'translate3d(0,'+((1-p)*extent).toFixed(1)+'px,0)',lower:'translate3d(0,'+(-10*p).toFixed(1)+'px,0) scale('+(1-.035*p).toFixed(4)+')',dim:'brightness('+(1-.08*p).toFixed(3)+')'};
}
function iosSwipeCommits(progress,velocity,distance=.35){return velocity>.35||(progress>distance&&velocity>-.1)}
function iosNavController(upper,lower,extent,cleanup){
  let anims=[],ended=false;
  const stop=()=>{anims.forEach(a=>a.cancel());anims=[]};
  const nav={upper,lower,extent,p:1,target:upper,gesture:false,
    set(p){nav.p=p;const f=iosNavFrame(p,extent);upper.style.transform=f.upper;lower.style.transform=f.lower;lower.style.filter=f.dim},
    run(to){
      const from=iosNavFrame(nav.p,extent),dest=iosNavFrame(to,extent),ms=iosReducedMotion()||!upper.animate?0:Math.round(IOS_NAV_MS*Math.max(.45,Math.abs(to-nav.p)));
      stop();nav.p=to;nav.target=to?upper:lower;
      for(const e of [upper,lower]){e.style.transform='';e.style.filter=''}
      if(!ms){nav.end();return Promise.resolve()}
      const o={duration:ms,easing:IOS_NAV_EASE,fill:'forwards'};
      const run=anims=[upper.animate([{transform:from.upper},{transform:dest.upper}],o),lower.animate([{transform:from.lower,filter:from.dim},{transform:dest.lower,filter:dest.dim}],o)];
      return Promise.allSettled(run.map(a=>a.finished)).then(()=>{if(anims===run)nav.end()});
    },
    end(){if(ended)return;ended=true;cleanup(nav.target);stop()}};
  return nav;
}
function iosSettingsTransition(view,upper,lower,upperScroll,lowerScroll){
  const body=view.querySelector('.setbody'),cs=getComputedStyle(body),pad=parseFloat(cs.paddingTop)||0,height=body.clientHeight;
  const pages=[[upper,upperScroll,'2'],[lower,lowerScroll,'1']].map(([el,scroll,z])=>({el,scroll,z,css:el.style.cssText}));
  for(const {el,scroll,z} of pages)Object.assign(el.style,{display:'block',position:'absolute',left:'0',right:'0',top:-scroll+'px',minHeight:(height+scroll)+'px',
    paddingTop:pad+'px',paddingLeft:cs.paddingLeft,paddingRight:cs.paddingRight,background:'var(--ios-settings-bg)',zIndex:z,willChange:'transform',transformOrigin:'top center',borderRadius:'24px 24px 0 0'});
  upper.style.boxShadow='0 -8px 28px rgba(0,0,0,.12)';
  body.style.overflow='hidden';body.scrollTop=0;view.classList.add('iosNavBusy');
  const nav=iosNavController(upper,lower,height,shown=>{
    for(const {el,css} of pages){el.style.cssText=css;el.style.display=el===shown?'block':'none'}
    const scroll=pages.find(p=>p.el===shown).scroll;
    body.style.overflow='';body.scrollTop=scroll;view.classList.toggle('iosScrolled',scroll>1);view.classList.remove('iosNavBusy');
    if(view._iosNav===nav)view._iosNav=null;
  });
  return view._iosNav=nav;
}
function iosSettingsPageMotion(view,leaving,next,nextScroll,direction){
  const nav=view._iosNav;
  if(nav){nav.upper.style.display=nav.lower.style.display='block';nav.gesture=false;nav.run(0);return}
  if(!leaving||!next||!view.classList.contains('on')||iosReducedMotion())return;
  const push=direction>0,motion=push?iosSettingsTransition(view,next,leaving.el,nextScroll,leaving.scroll):iosSettingsTransition(view,leaving.el,next,leaving.scroll,nextScroll);
  motion.p=push?0:1;motion.run(push?1:0);
}
function iosModelNav(){
  const upper=$('modelv'),lower=$('setv');
  upper._iosNav?.end();lower.inert=true;lower.style.transition='none';upper.classList.add('iosNavBusy');
  const nav=iosNavController(upper,lower,upper.getBoundingClientRect().height||innerHeight,()=>{
    for(const e of [upper,lower]){e.style.transform='';e.style.filter=''}
    lower.style.transition='';lower.inert=upper.classList.contains('on');upper.classList.remove('iosNavBusy');if(upper._iosNav===nav)upper._iosNav=null;
  });
  return upper._iosNav=nav;
}
function iosSpeed(at,time){let x0=at,t0=time,v=0;return {move(x,t){if(t-t0>=16){v=(x-x0)/(t-t0);x0=x;t0=t}},at(t){return t-t0>100?0:v}}}
function iosBindPageDrag(view,handle,{can,begin,commit}){
  let g=null;
  handle.addEventListener('touchstart',e=>{const t=e.touches[0];
    g=e.touches.length===1&&!e.target.closest('button,a,input')&&view.classList.contains('on')&&!view._iosNav&&can()
      ?{x:t.clientX,y:t.clientY,speed:iosSpeed(t.clientY,e.timeStamp),nav:null}:null},{passive:true});
  handle.addEventListener('touchmove',e=>{if(!g)return;const t=e.touches[0],dx=t.clientX-g.x,dy=t.clientY-g.y;
    if(!g.nav){if(Math.abs(dx)>10&&Math.abs(dx)>Math.abs(dy)){g=null;return}if(dy<8||dy<Math.abs(dx))return;g.nav=begin();if(!g.nav){g=null;return}}
    e.preventDefault();g.speed.move(t.clientY,e.timeStamp);g.nav.set(1-Math.max(0,dy)/g.nav.extent)},{passive:false});
  handle.addEventListener('touchend',e=>{const drag=g;g=null;if(!drag?.nav)return;
    if(iosSwipeCommits(1-drag.nav.p,drag.speed.at(e.timeStamp),.25))commit();else{drag.nav.gesture=false;drag.nav.run(1)}});
  handle.addEventListener('touchcancel',()=>{if(g?.nav){g.nav.gesture=false;g.nav.run(1)}g=null});
}
function iosBindSheetDrag(view,handle,dismiss,can=()=>true,dim=$('iosSheetDim')){
  let g=null;
  const release=commit=>{for(const e of [view,dim].filter(Boolean)){e.style.transition='';e.style.transform='';e.style.opacity=''}if(commit)dismiss()};
  handle.addEventListener('touchstart',e=>{const {clientX:x,clientY:y}=e.touches[0];
    g=e.touches.length===1&&!e.target.closest('button,a,input')&&view.classList.contains('on')&&!view._iosNav&&can()?{x,y,dy:0,speed:iosSpeed(y,e.timeStamp),on:false}:null},{passive:true});
  handle.addEventListener('touchmove',e=>{if(!g)return;const {clientX:x,clientY:y}=e.touches[0];g.dy=Math.max(0,y-g.y);
    if(!g.on){if(view._iosNav){g=null;return}if(g.dy<6||Math.abs(x-g.x)>g.dy)return;g.on=true;view.style.transition='none';if(dim)dim.style.transition='none'}
    e.preventDefault();g.speed.move(y,e.timeStamp);
    view.style.transform='translate3d(0,'+g.dy+'px,0)';if(dim)dim.style.opacity=String(Math.max(0,1-g.dy/view.offsetHeight))},{passive:false});
  handle.addEventListener('touchend',e=>{const drag=g;g=null;if(drag?.on)release(iosSwipeCommits(drag.dy/view.offsetHeight,drag.speed.at(e.timeStamp),.25))});
  handle.addEventListener('touchcancel',()=>{if(g?.on)release(false);g=null});
}
