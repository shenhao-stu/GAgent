// iOS navigation changes only presentation; leaving setup never stops phone control.
function iosBoardPresentation(state){
  if(!state||state.ok!==true)return {key:'iosPhoneUnknown',tone:'unknown'};
  if(!state.connected)return {key:state.paired?'iosPhoneReconnect':'iosPhoneConnect',tone:'setup'};
  if(!state.consent)return {key:'iosPhoneAuthorize',tone:'setup'};
  if(!state.hid_ready)return {key:'iosPhoneInput',tone:'setup'};
  if(!state.screen_sharing_active)return {key:'iosPhoneShare',tone:'setup'};
  if(!state.calibrated)return {key:'iosPhoneCalibrate',tone:'setup'};
  return {key:state.ready?'iosPhoneReady':'iosPhoneWaiting',tone:state.ready?'ready':'setup'};
}
let _iosBoardRefreshAt=0;
function refreshIOSDeviceStatus(force=true){
  if(!isIOSClient()||!GA.boardStatus)return;
  if(!force&&(document.hidden||Date.now()-_iosBoardRefreshAt<2000||!Array.from(document.querySelectorAll('[data-ios-board-state]')).some(e=>e.getClientRects().length&&!e.closest('[inert]'))))return;
  _iosBoardRefreshAt=Date.now();
  let state=null;try{state=JSON.parse(GA.boardStatus()||'null')}catch(e){}
  const presentation=iosBoardPresentation(state);
  document.querySelectorAll('[data-ios-board-state]').forEach(e=>{
    const value=t(presentation.key);if(e.textContent!==value)e.textContent=value;e.dataset.tone=presentation.tone;
  });
}
function initIOSNavigation(){
  if(!isIOSClient()||window.GAIOS)return;
  document.documentElement.classList.add('iosApp');
  Object.assign(I18N.zh,{iosAssistant:'助手',iosComputer:'电脑',iosThisPhone:'本机',iosSwitchComputer:'切换到电脑对话',iosSwitchPhone:'切换到本机对话',iosConnections:'设备与连接',iosPhone:'iPhone 操作',
    memHint:'这里保存可查看和编辑的记忆与操作指南。',iosPhoneUnknown:'查看连接',iosPhoneConnect:'连接设备',iosPhoneReconnect:'等待重连',
    iosPhoneAuthorize:'开启操作授权',iosPhoneInput:'连接无线键鼠',iosPhoneShare:'开启屏幕共享',iosPhoneCalibrate:'完成指针校准',
    iosPhoneWaiting:'等待新画面',iosPhoneReady:'操作就绪',
    iosCloseSidebar:'关闭侧栏',iosAssistantTitle:'有什么可以帮你？',iosAssistantHint:'从一个问题，到一件事的完成。',
    iosHeroFoot:'点选建议只会填入输入框，发送后才开始执行',iosNewChatHint:'点这里开始新对话',
    iosRecipients:'谁会接收',iosSharedContent:'与 AI 对话',iosOptionalComputer:'连接电脑',iosOptionalPermissions:'设备权限与屏幕',
    iosDataStorage:'数据保存',iosDataChoice:'你的选择',
    iosTaskInterrupted:'已中断',iosTaskFailed:'任务未完成',iosTaskFailedSteps:'任务未完成 · {n} 条过程记录',
    provListHint:'密钥保存在本机，调用模型时只发送给对应服务商。同一服务商可添加多个模型，在输入框下方切换。',
    welcomeP:'添加一个模型服务商即可开始。密钥保存在本机，只发送给对应服务商。',
    iosDone:'完成',iosProxyTunnel:'检测到 VPN 隧道（{i}），GAgent 的网络请求已由它接管，无需再填本地代理。若要按代理 App 的规则分流，请在其设置中开启本地 HTTP 代理后重试。',
    t_proxyNone:'未发现系统代理或 VPN 隧道。'});
  Object.assign(I18N.en,{iosAssistant:'Assistant',iosComputer:'Computer',iosThisPhone:'iPhone',iosSwitchComputer:'Switch to computer chat',iosSwitchPhone:'Switch to iPhone chat',iosConnections:'Devices & connections',iosPhone:'iPhone control',
    memHint:'View and edit saved memories and guides here.',iosPhoneUnknown:'Check connection',iosPhoneConnect:'Connect device',iosPhoneReconnect:'Reconnecting',
    iosPhoneAuthorize:'Enable control',iosPhoneInput:'Connect wireless input',iosPhoneShare:'Start screen sharing',iosPhoneCalibrate:'Calibrate pointer',
    iosPhoneWaiting:'Waiting for a frame',iosPhoneReady:'Ready',
    iosCloseSidebar:'Close sidebar',iosAssistantTitle:'What can I help with?',iosAssistantHint:'From a question to a task, all in one place.',
    iosHeroFoot:'Suggestions only fill the message box. Nothing runs until you send.',iosNewChatHint:'Tap here to start a new chat',
    iosRecipients:'Who receives it',iosSharedContent:'Conversations with AI',iosOptionalComputer:'Computer connections',iosOptionalPermissions:'Device and screen access',
    iosDataStorage:'Data retention',iosDataChoice:'Your choices',
    iosTaskInterrupted:'Stopped',iosTaskFailed:'Task not completed',iosTaskFailedSteps:'Task not completed · {n} progress entries',
    provListHint:'Keys stay on this iPhone and are sent only to their provider when a model is used. Add several models per provider and switch below the message box.',
    welcomeP:'Add a model provider to get started. Keys stay on this iPhone and are sent only to their provider.',
    iosDone:'Done',iosProxyTunnel:'A VPN tunnel ({i}) is active and already carries GAgent’s traffic, so no local proxy is needed. To route by your proxy app’s rules, enable its local HTTP proxy and try again.',
    t_proxyNone:'No system proxy or VPN tunnel found.'});
  const historyIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16M13 9h4M13 13h4"/></svg>';
  for(const history of [document.querySelector('#hdr>.iconbtn'),$('pcMenuBtn')])if(history)history.innerHTML=historyIcon;
  function sync(){
    const pc=$('pcView'),settings=$('setv').classList.contains('on')||$('setv').classList.contains('iosClosing'),current=settings?'settings':pc&&pc.classList.contains('on')?'computer':'assistant';
    document.body.dataset.iosPage=current;
    $('app').inert=current!=='assistant';$('app').setAttribute('aria-hidden',String(current!=='assistant'));
    if(pc){pc.inert=current!=='computer';pc.setAttribute('aria-hidden',String(current!=='computer'));}
    if(!settings)try{localStorage.setItem('ga.ios.destination',current)}catch(e){}
    if(settings)refreshIOSDeviceStatus();
  }
  function navigate(destination){
    closeDrawer();
    if(destination==='settings')openSettings();
    else{closeSettings();if(destination==='computer')PCLINK.openView();else PCLINK.closeView();}
    sync();refreshIOSDeviceStatus();
  }
  // The WebView outlives appearance changes, so "follow system" must track them live.
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{
    if(theme!=='system')return;applyTheme()});
  // The keyboard and a growing composer resize the chat without scrolling it; re-judge the return control.
  let restingHeight=window.innerHeight,viewportWidth=window.innerWidth;
  const editing=()=>document.activeElement?.matches('input,textarea,[contenteditable="true"]');
  const rememberHomeHeight=()=>{
    if(editing()||document.documentElement.classList.contains('iosKeyboard'))return;
    const style=getComputedStyle(chat),height=chat.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);
    document.documentElement.style.setProperty('--ios-home-height',Math.max(0,height)+'px');
  };
  if(window.ResizeObserver)new ResizeObserver(()=>{rememberHomeHeight();updateScrollNav()}).observe(chat);
  const observer=new MutationObserver(sync);
  observer.observe($('setv'),{attributes:true,attributeFilter:['class']});
  if($('pcView'))observer.observe($('pcView'),{attributes:true,attributeFilter:['class']});
  let viewportFrame=0;
  const keyboard=()=>{viewportFrame=0;const viewport=window.visualViewport,root=document.documentElement;
    const height=viewport?viewport.height:window.innerHeight,wasKeyboard=root.classList.contains('iosKeyboard'),focused=editing();
    if(viewportWidth!==innerWidth||(!focused&&!wasKeyboard)){restingHeight=Math.max(innerHeight,height);viewportWidth=innerWidth}
    const keyboardUp=restingHeight-height>(wasKeyboard?1:120)&&(focused||wasKeyboard);
    root.classList.toggle('iosKeyboard',!!keyboardUp);
    if(!keyboardUp&&!focused)restingHeight=Math.max(innerHeight,height);
    root.style.setProperty('--ios-viewport-height',height+'px');
    root.style.setProperty('--ios-viewport-top',(viewport?viewport.offsetTop:0)+'px');
    if(!emptyEl)scroll();updateScrollNav();revealField();
  };
  // Keep focused settings fields inside their scroll container as the keyboard changes height.
  const revealField=()=>requestAnimationFrame(()=>{
    const field=document.activeElement,body=field&&field.closest('.setbody,.modalBody,.shBody');
    if(!body||!field.matches('input,textarea,select'))return;
    const r=field.getBoundingClientRect(),box=body.getBoundingClientRect(),inset=Math.max(12,parseFloat(getComputedStyle(body).scrollPaddingTop)||0);
    if(r.bottom>box.bottom-12)body.scrollTop+=r.bottom-box.bottom+12;
    else if(r.top<box.top+inset)body.scrollTop+=r.top-box.top-inset;
  });
  document.addEventListener('focusin',revealField);
  const scheduleViewport=()=>{if(!viewportFrame)viewportFrame=requestAnimationFrame(keyboard)};
  if(window.visualViewport){visualViewport.addEventListener('resize',scheduleViewport);visualViewport.addEventListener('scroll',scheduleViewport)}
  window.addEventListener('resize',scheduleViewport);rememberHomeHeight();keyboard();
  iosSidebarChrome($('drawer'),'history',closeDrawer,()=>document.getElementById('drawer').classList.contains('on'),$('drawer'));
  const account=$('drawer').querySelector('.dwUser');if(account){account.dataset.i18nAria='settings';account.onclick=()=>openSettings();}
  initIOSSettings();
  window.GAIOS={navigate,refresh:refreshIOSDeviceStatus};
  let initial='assistant';try{if(localStorage.getItem('ga.ios.destination')==='computer')initial='computer'}catch(e){}
  applyI18n();navigate(initial);syncIOSNewConversation();
}

function isIOSClient(){return !!(window.GA&&GA.platform==='ios')}
const IOS_COMPOSE_ICON='<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-7M16 3l5 5M10 14l-1 4 4-1L22 8l-5-5z"/></svg>';
function syncIOSNewConversation(){
  if(!isIOSClient())return;
  const button=$('hdrMoreBtn');if(!button)return;
  button.classList.add('iosNewConversation');button.hidden=false;
  button.title=t('newChat');button.setAttribute('aria-label',t('newChat'));button.setAttribute('data-i18n-aria','newChat');
  if(button.dataset.icon!=='compose'){button.innerHTML=IOS_COMPOSE_ICON;button.dataset.icon='compose'}
  button.onclick=newConversation;
  if(!button.hidden&&window.GAIOS)iosHintOnce(button,'newChat','iosNewChatHint');
}
// A one-time callout explains an icon-only control without taking header space.
function iosHintOnce(anchor,id,key){
  const flag='ga.ios.hint.'+id;
  try{if(localStorage.getItem(flag)||!anchor.getClientRects().length||anchor.closest('[inert]'))return;localStorage.setItem(flag,'1')}catch(e){return}
  const tip=document.createElement('div'),r=anchor.getBoundingClientRect();tip.className='iosHint';tip.setAttribute('role','status');tip.textContent=t(key);
  tip.style.top=Math.round(r.bottom+10)+'px';tip.style.right=Math.max(8,Math.round(innerWidth-r.right))+'px';document.body.appendChild(tip);
  const close=()=>{removeEventListener('pointerdown',close,true);tip.classList.add('out');setTimeout(()=>tip.remove(),240)};
  addEventListener('pointerdown',close,true);setTimeout(close,4500);
}
function iosReducedMotion(){return matchMedia('(prefers-reduced-motion: reduce)').matches}
// Closing remains painted until its transition (or the supplied motion) ends; reopening cancels only that close.
function iosPresentView(view,show,motion){
  view._iosClose?.(false);
  if(view.id==='setv')document.documentElement.classList.toggle('iosSheetUp',!!show);
  if(show){
    if(!view.classList.contains('on')&&!view.classList.contains('iosClosing'))view._iosFocusReturn=document.activeElement;
    iosPrepareModal();view.inert=false;view.setAttribute('role','dialog');view.setAttribute('aria-modal','true');view.setAttribute('aria-hidden','false');
    const heading=view.querySelector('.ttl,h3');if(heading?.id)view.setAttribute('aria-labelledby',heading.id);
    view.classList.remove('iosClosing');view.classList.add('on');
    if(heading){heading.tabIndex=-1;requestAnimationFrame(()=>{if(view.classList.contains('on'))heading.focus({preventScroll:true})})}
    return;
  }
  if(!view.classList.contains('on')&&!view.classList.contains('iosClosing'))return;
  iosPrepareModal();view.inert=true;view.setAttribute('aria-hidden','true');view.removeAttribute('aria-modal');
  view.classList.add('iosClosing');view.classList.remove('on');
  let timer;
  const ended=e=>{if(e.target===view&&e.propertyName==='transform')finish()};
  const finish=(closed=true)=>{if(view._iosClose!==finish)return;view._iosClose=null;clearTimeout(timer);view.removeEventListener('transitionend',ended);
    if(!closed)return;view.classList.remove('iosClosing');
    const target=view._iosFocusReturn;view._iosFocusReturn=null;
    requestAnimationFrame(()=>{
      if(view.classList.contains('on')||view.classList.contains('iosClosing')||document.querySelector('#modalMask.on,.sheet.on,#modelv.on'))return;
      const valid=target&&target!==document.body&&target.isConnected&&!target.closest('[inert],[aria-hidden="true"]')&&target.getClientRects().length;
      const next=valid?target:document.querySelector('#setv.on .setbar>.iconbtn:not([hidden]),#setv.on .iosBarDone,#pcView.on #pcMenuBtn')||document.querySelector('#hdr>.iconbtn');
      if(!next)return;
      next.dataset.iosQuietFocus='';next.addEventListener('blur',()=>delete next.dataset.iosQuietFocus,{once:true});
      next.focus({preventScroll:true});
    });
  };
  view._iosClose=finish;
  if(iosReducedMotion())finish();else if(motion)motion.then(()=>finish());else{view.addEventListener('transitionend',ended);timer=setTimeout(finish,650)}
}
function iosPrepareModal(){if(isIOSClient()&&document.activeElement&&typeof document.activeElement.blur==='function')document.activeElement.blur()}

function iosFinalFailed(value){
  // Engine error sentinels, never ordinary prose mentioning an HTTP error or a fenced example.
  const text=String(value||'').replace(/```[\s\S]*?```/g,'').trim();
  return /^(?:!!!Error:|\[Error:)/.test(text)||/(?:^|\n)(?:!!!Error:[^\n]*|\[!!! 流异常中断 [^\n]* !!!\])\s*$/.test(text);
}
function iosModelIssue(value,language){
  const text=cleanStepText(String(value||''));
  if(!/^!!!Error:\s*HTTP\s+\d{3}\b/.test(text))return null;
  const en=language==='en';let title,hint;
  if(/Weekly\/Monthly Limit Exhausted|insufficient[_ ](?:quota|credits|balance)|quota[_ ]exceeded|额度.*(?:耗尽|用完)|HTTP 402\b/i.test(text)){
    title=en?'Model quota exhausted':'模型额度已用完';
    hint=en?'Choose an available model, or restore your allowance with the provider.':'选择其他可用模型，或在服务商处恢复额度。';
  }else if(/^!!!Error:\s*HTTP 429\b/.test(text)){
    title=en?'Too many requests':'请求暂时受限';
    hint=en?'Wait before trying again, or choose another model.':'稍后再试，或选择其他模型。';
  }else if(/^!!!Error:\s*HTTP 401\b/.test(text)){
    title=en?'Model sign-in failed':'模型授权失败';
    hint=en?'Check the provider settings, or choose another model.':'检查服务商配置，或选择其他可用模型。';
  }else return null;
  return {title,hint,details:text};
}
function iosRenderModelIssue(body,value){
  const issue=iosModelIssue(value,lang);if(!issue)return false;
  const make=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node};
  const card=make('section','');card.className='iosModelIssue';
  card.append(make('h4',issue.title),make('p',issue.hint));
  const choose=make('button',lang==='en'?'Choose another model':'选择其他模型');choose.type='button';choose.onclick=()=>openModelSheet();
  card.append(choose);
  const detail=make('details','');detail.append(make('summary',lang==='en'?'Error details':'错误详情'),make('pre',issue.details));card.append(detail);
  body.replaceChildren(card);return true;
}

function iosTaskOutcome(failure,final){
  if(failure===1)return 'iosTaskInterrupted';
  return failure===2||iosFinalFailed(final)?'iosTaskFailed':'';
}
function iosPollStatus(payload,failure){const outcome=payload.running===false?iosTaskOutcome(failure,payload.final):'';return outcome?t(outcome):payload.status}
function iosStatusText(value,language){
  const text=value||'',key=String(text).trim().toLowerCase();
  // Only protocol states are translated; model names and descriptive statuses remain intact.
  const labels={idle:['就绪','Ready'],ready:['就绪','Ready'],running:['执行中','Running'],
    starting:['启动中','Starting'],booting:['启动中','Starting'],loading:['加载中','Loading'],
    done:['已完成','Completed'],completed:['已完成','Completed'],stopped:['已停止','Stopped'],
    aborted:['已中止','Stopped'],error:['出现错误','Error']};
  return Object.prototype.hasOwnProperty.call(labels,key)?labels[key][language==='en'?1:0]:text;
}

// Shared sidebar chrome; visibility is derived from the existing navigation state.
function iosSidebarChrome(side,title,close,isOpen,owner){
  const head=document.createElement('div');head.className='iosSidebarHead';
  const heading=document.createElement('h2');heading.dataset.i18n=title;heading.textContent=t(title);
  const button=document.createElement('button');button.type='button';button.className='iconbtn';
  button.dataset.i18nAria='iosCloseSidebar';button.setAttribute('aria-label',t('iosCloseSidebar'));
  button.innerHTML='<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="m7 7 10 10M7 17 17 7"/></svg>';
  button.onclick=close;head.append(heading,button);side.prepend(head);
  const bar=side.querySelector('.dwUserBar'),settings=bar.querySelector('.dwIcon[data-i18n-aria="settings"]');
  const language=bar.querySelector('[data-i18n-aria="language"]');
  language.classList.add('iosSidebarLanguage');language.removeAttribute('data-i18n-aria');
  const appearance=document.createElement('button');appearance.type='button';appearance.className='dwIcon iosSidebarTheme';
  appearance.innerHTML='<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></svg>';
  appearance.onclick=()=>{theme=document.documentElement.dataset.theme==='dark'?'light':'dark';LS.set('theme',theme);applyTheme();refreshThemeVal()};
  bar.insertBefore(language,settings);bar.insertBefore(appearance,settings);iosSyncSidebarPreferences();
  const sync=()=>{const open=isOpen();if(!open&&side.contains(document.activeElement))document.activeElement.blur();side.inert=!open;side.setAttribute('aria-hidden',String(!open))};
  new MutationObserver(sync).observe(owner,{attributes:true,attributeFilter:['class']});
  window.addEventListener('resize',sync);sync();
}

function iosSyncSidebarPreferences(){
  if(!isIOSClient())return;
  const dark=document.documentElement.dataset.theme==='dark';
  document.querySelectorAll('.iosSidebarLanguage').forEach(button=>{
    button.title=lang==='en'?'Switch to Chinese':'切换到英文';button.setAttribute('aria-label',button.title);
  });
  document.querySelectorAll('.iosSidebarTheme').forEach(button=>{
    button.querySelector('svg').innerHTML=dark?'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>':'<path d="M20.5 13.5A8.5 8.5 0 0 1 10.5 3.5a8.5 8.5 0 1 0 10 10Z"/>';
    button.title=lang==='en'?(dark?'Switch to light appearance':'Switch to dark appearance'):(dark?'切换到浅色模式':'切换到深色模式');button.setAttribute('aria-label',button.title);
  });
}
