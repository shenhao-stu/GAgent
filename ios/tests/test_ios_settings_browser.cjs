// Offline integration test: real WebUI, fixture bridge, no external requests or real credentials.
const fs=require('fs'),http=require('http'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../..'),web=process.env.IOS_SETTINGS_WEB_ROOT||root+'/app/src/main/assets/ga_runtime/webui';
const out=process.env.IOS_SETTINGS_ARTIFACTS||fs.mkdtempSync(path.join(require('os').tmpdir(),'gagent-settings-'));
fs.mkdirSync(out,{recursive:true});
const base=fs.readFileSync(web+'/assets/shim.js','utf8');
const bridge=fs.readFileSync(root+'/ios/GAgent/ios_bridge.js','utf8');
const boot=`${base}\nconst demoGA=window.GA;delete window.GA;window.demoState={paired:true,connected:true,messages:false,board:{ok:true,connected:true,consent:true,hid_ready:true,mirroring:true,calibrated:true,ready:true},calls:[]};
window.prompt=(sentinel,payload)=>{const q=JSON.parse(payload);const [cmd]=q.args;const s=window.demoState;
if(q.kind==='native'){if(q.fn==='boardStatus')return JSON.stringify(s.board);if(q.fn==='boardSetup'){s.calls.push('boardSetup');return ''}if(q.fn==='isDark')return 'false';return demoGA[q.fn]?String(demoGA[q.fn](...q.args)||''):''}
if(q.fn==='ready')return 'ok';if(q.fn==='caps')return '{}';
if(q.fn==='select_model'){s.calls.push('select_model');return JSON.stringify({ok:true})}
if(q.fn==='poll')return JSON.stringify({running:false,status:'就绪',gen:1,nsteps:0,steps:[],hist:[]});
if(q.fn==='send'){
s.calls.push(cmd);
if(cmd==='/ios.proxy.status')return JSON.stringify({proxy:s.proxy||''});
if(cmd.startsWith('/ios.proxy.probe '))return '{"job":"fixture-proxy"}';
if(cmd==='/jobresult fixture-proxy')return JSON.stringify(s.proxyPending?{pending:true}:{result:JSON.stringify({proxy:s.proxyResult||''})});
if(cmd.startsWith('/proxy ')){s.proxy=cmd==='/proxy clear'?'':cmd.slice(7);return s.proxy?'代理已设置: '+s.proxy:'代理已清除'}
if(cmd==='/ios.consent.status')return JSON.stringify({ok:true,pcAccepted:true,accepted:true,needsRefresh:false,receivers:[]});
if(cmd.startsWith('/models '))return s.modelsPending?'{"job":"fixture-models"}':JSON.stringify(s.models||{});
if(cmd==='/jobresult fixture-models')return JSON.stringify(s.modelsPending?{pending:true}:{result:JSON.stringify(s.models||{})});
if(cmd.startsWith('/pclink.')){
if(cmd.startsWith('/pclink.status')||cmd.startsWith('/pclink.resume'))return JSON.stringify({paired:s.paired,connected:s.connected});
if(cmd.includes('/messages'))return JSON.stringify({title:'(empty)',tasks:s.messages?[{i:0,input:'检查项目并总结当前进度',steps:[{j:0,title:'检查完毕',n:8}]}]:[],sig:s.messages?'a':'b',run:false});
if(cmd.includes('/seg/'))return JSON.stringify({content:'已完成项目检查。\\n\\n- 测试正常\\n- 没有待处理错误',off:0,n:36});
if(cmd.includes('/api/peers'))return JSON.stringify(s.connected?[{name:'reflect_mac_terminal-49122',title:'(empty)',n_msgs:s.messages?2:0,caps:['get','put'],run:false}]:{error:'offline'});
return '{}';}
if(['/config','/storageinfo'].includes(cmd)||/^\\/(kv\\.|lang|clear)/.test(cmd))return demoGA.send(cmd);
return '{}';}
return demoGA[q.fn]?demoGA[q.fn](...q.args):'';};
localStorage.setItem('ga.lang','"zh"');localStorage.setItem('ga.authSkipped','true');localStorage.setItem('ga.privacyConsent','true');localStorage.setItem('ga.theme','"light"');localStorage.setItem('ga.ios.destination','computer');
${bridge}`;

(async()=>{
const assert=require('node:assert/strict'),results=[],errors=[];
const server=http.createServer((req,res)=>{const p=path.join(web,req.url.split('?')[0]==='/'?'index.html':req.url.split('?')[0]);try{res.setHeader('Content-Type',p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(p))}catch(e){res.statusCode=404;res.end('')}});await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const page=await browser.newPage({viewport:{width:430,height:932},isMobile:true,hasTouch:true,deviceScaleFactor:2});page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());await page.addInitScript({content:boot});await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForTimeout(400);
await page.evaluate(()=>{GAIOS.navigate('settings')});
async function check(name,fn){await fn();results.push({check:name,passed:true})}
async function capture(name){await page.waitForTimeout(260);await page.evaluate(()=>$('toast').classList.remove('on'));await page.waitForTimeout(250);const geometry=await page.evaluate(()=>({width:innerWidth,bodyWidth:document.documentElement.scrollWidth,settings:document.getElementById('setv').getBoundingClientRect().toJSON(),content:document.querySelector('#setv>.setbody').getBoundingClientRect().toJSON(),panel:document.getElementById('setv').dataset.panel}));assert(geometry.bodyWidth<=geometry.width,JSON.stringify(geometry));await page.screenshot({path:out+'/'+name+'.png'});results.push({capture:name,...geometry})}
const settle=()=>page.waitForTimeout(520);
await check('failover preserves excluded models and order, supports accessible moves and cancels interrupted drags',async()=>{
  const saved=await page.evaluate(()=>({providers,active,foCfg}));
  await page.evaluate(()=>{
    providers=[['p1','Primary','gpt-6.1-sol'],['p2','Z.ai','glm-5.3-flash'],['p3','Extra','gpt-6.1-sol-long-name']].map(([id,name,model])=>({id,name,model,type:'oai',enabled:true,apikey:'fixture-only',apibase:'https://example.test/v1'}));
    active={pid:'p1',model:'gpt-6.1-sol'};foCfg={enabled:false,llm_nos:['Primary','Z.ai'],max_retries:3,base_delay:.5};openFailoverSheet();
  });await settle();await capture('failover-off');
  assert.deepEqual(await page.locator('#foChain .sub').allTextContents(),['首选 · Primary','备选 1 · Z.ai','不参与 · Extra']);
  await page.locator('#foEnabledSw').click();await page.locator('#foEnabledSw').click();await page.locator('#foEnabledSw').click();
  assert.deepEqual(await page.evaluate(()=>foChain.map(it=>it.on)),[true,true,false]);
  assert.equal(await page.locator('#iosFoState').textContent(),'已开启 · 尚未用于当前对话');
  assert(await page.locator('#iosFoUse').isVisible());
  await page.locator('#iosFoUse').click();assert.equal(await page.locator('#iosFoState').textContent(),'当前对话正在使用');
  assert(!(await page.locator('#iosFoUse').isVisible()));
  await page.locator('#iosFoEdit').click();await page.locator('#foChain .iosFoMove').nth(1).click();
  assert.deepEqual(await page.evaluate(()=>foCfg.llm_nos),['Z.ai','Primary']);
  const grip=page.locator('#foChain .foGrip').nth(0);await grip.focus();await page.keyboard.press('ArrowDown');
  assert.deepEqual(await page.evaluate(()=>foCfg.llm_nos),['Primary','Z.ai']);
  await page.evaluate(()=>{
    const grip=$('foChain').querySelector('.foGrip'),r=grip.getBoundingClientRect();
    grip.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientY:r.y+20}));
    document.dispatchEvent(new PointerEvent('pointermove',{clientY:r.y+300}));
    document.dispatchEvent(new PointerEvent('pointercancel'));
  });assert.deepEqual(await page.evaluate(()=>foCfg.llm_nos),['Primary','Z.ai']);
  await page.evaluate(()=>{
    const rows=[...$('foChain').children];rows[0].style.paddingBottom='55px';
    const a=rows[0].getBoundingClientRect(),b=rows[2].getBoundingClientRect();
    rows[0].querySelector('.foGrip').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientY:a.y+20}));
    document.dispatchEvent(new PointerEvent('pointermove',{clientY:b.bottom+20}));document.dispatchEvent(new PointerEvent('pointerup'));
  });assert.deepEqual(await page.evaluate(()=>foChain.map(it=>it.id)),['p2','p3','p1']);
  await page.evaluate(()=>iosMoveFailover(2,0,'.foGrip'));
  await capture('failover-reorder');await page.locator('#iosFoEdit').click();
  await page.locator('#foAdv .advHead').click();assert.equal(await page.locator('#foAdv .advHead').getAttribute('aria-expanded'),'true');
  await page.locator('#foDelay').fill('0');await page.waitForTimeout(600);assert.equal(await page.evaluate(()=>foCfg.base_delay),0);
  await capture('failover-advanced');
  for(const config of [{width:430,height:932,theme:'dark',lang:'zh',size:17},{width:320,height:568,theme:'light',lang:'en',size:22}]){
    await page.setViewportSize({width:config.width,height:config.height});
    await page.evaluate(c=>{setLang(c.lang);document.documentElement.dataset.theme=c.theme;$('failoverSheet').style.fontSize=c.size+'px';iosUpdateFailover()},config);
    await capture('failover-'+config.width+'-'+config.theme);
    const overflow=await page.locator('#failoverSheet .shBody').evaluate(e=>e.scrollWidth>e.clientWidth);assert(!overflow);
    const targets=await page.locator('#failoverSheet button:visible').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().height));assert(targets.every(h=>h>=44));
  }
  await page.setViewportSize({width:430,height:932});
  await page.evaluate(()=>{foChain.forEach(it=>it.on=false);foPersist();openFailoverSheet()});
  assert.deepEqual(await page.evaluate(()=>foChain.map(it=>it.on)),[false,false,false]);
  assert.equal(await page.locator('#foEnabledSw').getAttribute('aria-checked'),'false');
  await page.locator('#foEnabledSw').click();assert.deepEqual(await page.evaluate(()=>foChain.map(it=>it.on)),[true,true,true]);
  await page.evaluate(s=>{providers=s.providers;active=s.active;foCfg=s.foCfg;setLang('zh');document.documentElement.dataset.theme='light';$('failoverSheet').style.fontSize='';closeSheets()},saved);await settle();
});
if(process.env.IOS_SETTINGS_FOCUS==='failover'){
  assert.deepEqual(errors,[]);fs.writeFileSync(out+'/ui-results.json',JSON.stringify({results,errors},null,2));
  console.log(JSON.stringify({checks:results.filter(r=>r.check).length,screenshots:results.filter(r=>r.capture).length,errors}));
  await browser.close();server.close();return;
}
await check('home suggestions stay editable and never submit a task',async()=>{
  await page.evaluate(()=>{GAIOS.navigate('assistant');newConversation()});await settle();
  const chips=page.locator('#heroChips .heroChip');assert.equal(await chips.count(),4);
  const before=await page.evaluate(()=>({running,count:curConvo?.msgs?.length||0}));
  assert.equal(await page.locator('#empty .gaWordmark').textContent(),'GAgent');
  await capture('home-assistant-light');await chips.first().click();
  assert.match(await page.locator('#in').inputValue(),/iPhone/);
  assert.deepEqual(await page.evaluate(()=>({running,count:curConvo?.msgs?.length||0})),before);
  await page.evaluate(()=>{inp.value='';inp.blur()});
});
await check('home and PC start cards reflow at small and large sizes',async()=>{
  for(const c of [{width:320,height:568,theme:'light',size:16},{width:430,height:932,theme:'dark',size:20}]){
    await page.setViewportSize({width:c.width,height:c.height});
    await page.evaluate(c=>{document.documentElement.dataset.theme=c.theme;document.documentElement.style.fontSize=c.size+'px'},c);
    await settle();await capture('home-assistant-'+c.width+'-'+c.theme);
    const toolbar=await page.evaluate(()=>['btn','voiceBtn','attachBtn'].map(id=>document.getElementById(id).getBoundingClientRect().y));assert(Math.max(...toolbar)-Math.min(...toolbar)<10,'Composer actions must stay on one row');
    assert(await page.locator('#heroChips .heroChip').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44)));
    await page.evaluate(()=>GAIOS.navigate('computer'));await page.waitForFunction(()=>!!document.querySelector('.pcStart'));
    await settle();await capture('home-computer-'+c.width+'-'+c.theme);
    assert.equal(await page.locator('.pcStarterList button>svg').count(),4);
    await page.evaluate(()=>GAIOS.navigate('assistant'));await settle();
  }
  await page.setViewportSize({width:430,height:932});
  await page.evaluate(()=>{document.documentElement.dataset.theme='light';document.documentElement.style.fontSize='';GAIOS.navigate('settings')});
});

await check('both sidebars keep search and account controls fixed, and hide closed fields',async()=>{
  await page.evaluate(()=>{GAIOS.navigate('assistant');convos=Array.from({length:35},(_,i)=>({id:'layout-'+i,title:'项目研究与迭代计划 · 第 '+(i+1)+' 个会话',msgs:[],ts:Date.now()-i*3600e3}));renderDrawer()});
  for(const c of [{width:320,height:568,theme:'light',size:16},{width:430,height:932,theme:'dark',size:20}]){
    await page.setViewportSize({width:c.width,height:c.height});await page.evaluate(c=>{document.documentElement.dataset.theme=c.theme;document.documentElement.style.fontSize=c.size+'px'},c);
    for(const kind of ['local','computer']){
      await page.evaluate(kind=>{GAIOS.navigate(kind==='local'?'assistant':'computer');if(kind==='local')openDrawer();else document.getElementById('pcView').classList.add('side')},kind);await settle();
      const id=kind==='local'?'drawer':'pcSide';
      const layout=await page.locator('#'+id).evaluate(e=>{const box=e.getBoundingClientRect(),head=e.querySelector('.iosSidebarHead').getBoundingClientRect(),search=e.querySelector('.dwSearch').getBoundingClientRect(),list=e.querySelector('.dwList,#pcSideList').getBoundingClientRect(),foot=e.querySelector('.dwUserBar').getBoundingClientRect();return {inert:e.inert,box:box.toJSON(),head:head.toJSON(),search:search.toJSON(),list:list.toJSON(),foot:foot.toJSON(),height:innerHeight}});
      assert(!layout.inert);assert(layout.head.bottom<=layout.search.top+1);assert(layout.search.bottom<=layout.list.top+1);assert(layout.list.bottom<=layout.foot.top+1);assert(layout.foot.bottom<=layout.height+1);assert(layout.box.right<=c.width-40);
      await capture('sidebar-'+kind+'-'+c.width+'-'+c.theme);
      await page.locator('#'+id+' input').focus();await page.locator('#'+id+' .iosSidebarHead button').click();await settle();
      assert.equal(await page.locator('#'+id).evaluate(e=>e.inert&&!e.contains(document.activeElement)),true);
    }
  }
  await page.setViewportSize({width:430,height:932});await page.evaluate(()=>{document.documentElement.dataset.theme='light';document.documentElement.style.fontSize='';GAIOS.navigate('assistant');document.documentElement.classList.add('iosKeyboard')});await settle();await capture('home-keyboard');
  assert.equal(await page.locator('#heroChips').isVisible(),true);
  await page.evaluate(()=>{document.documentElement.classList.remove('iosKeyboard');GAIOS.navigate('settings')});
});
if(process.env.IOS_SHELL_PREVIEW){console.log(JSON.stringify({preview:true,checks:results.filter(r=>r.check).length,errors}));await browser.close();server.close();return}

await settle();await capture('after-home');
await page.locator('#iosAppVersion').scrollIntoViewIfNeeded();await settle();await capture('after-about');
await page.evaluate(()=>document.querySelector('#setv .setbody').scrollTop=0);await settle();
await check('one presentation module, connection entries grouped once at top',async()=>{
  assert.equal(await page.locator('#iosBoardSetup').count(),1);
  assert.equal(await page.locator('#iosSetvDone').count(),1);
  assert.equal(await page.locator('#homePanel>:first-child').evaluate(e=>e.id),'iosConnections');
  assert.equal(await page.locator('#iosConnectionCard #pcLinkRow').count(),1);
  assert.equal(await page.locator('#iosConnectionCard #iosProxySwitch').count(),1);
  assert.equal(await page.locator('#proxyDetectBtn').count(),0);
  await page.evaluate(()=>initIOSSettings());assert.equal(await page.locator('#iosSetvDone').count(),1);
});
await check('iOS proxy enables only after a successful test and ignores a cancelled result',async()=>{
  const toggle=page.locator('#iosProxySwitch'),state=page.locator('#iosProxyState');
  await page.evaluate(()=>{demoState.proxyPending=true;demoState.proxyResult='http://127.0.0.1:1082'});
  await toggle.click();assert.match(await state.textContent(),/正在检测/);
  await toggle.click();await page.evaluate(()=>{demoState.proxyPending=false});
  await page.waitForTimeout(450);
  assert.equal(await toggle.getAttribute('aria-checked'),'false');
  assert.equal(await page.evaluate(()=>demoState.proxy),'');
  await toggle.click();await page.waitForFunction(()=>$('iosProxyState').textContent==='代理已开启');
  assert.equal(await page.evaluate(()=>demoState.proxy),'http://127.0.0.1:1082');
  await toggle.click();assert.equal(await state.textContent(),'直连');
  await page.evaluate(()=>{demoState.proxyResult=''});
  await toggle.click();await page.waitForFunction(()=>$('iosProxyState').textContent.includes('保持直连'));
  assert.equal(await toggle.getAttribute('aria-checked'),'false');
  await capture('proxy-direct-fallback');
});
await check('child opens vertically and restores parent scroll on return',async()=>{
  await page.evaluate(()=>document.querySelector('#setv>.setbody').scrollTop=200);
  const before=await page.locator('#setv>.setbody').evaluate(e=>e.scrollTop);
  await page.evaluate(()=>openProviders());await page.waitForTimeout(60);
  const frame=await page.locator('#provListPanel').evaluate(e=>{const m=new DOMMatrix(getComputedStyle(e).transform);return {x:m.m41,y:m.m42}});
  assert.equal(frame.x,0);assert(frame.y>0);results.push({motion:'providers-enter',frame});
  await settle();await capture('after-providers-list');
  await page.locator('#setv .setbar>.iconbtn').first().click();await page.waitForTimeout(60);
  const exit=await page.locator('#provListPanel').evaluate(e=>new DOMMatrix(getComputedStyle(e).transform).m42);assert(exit>0);
  await settle();assert.equal(await page.locator('#setv>.setbody').evaluate(e=>e.scrollTop),before);
  assert.equal(await page.locator('#setv').evaluate(e=>e.dataset.panel),'homePanel');
});
await check('rapid route changes and close/reopen leave one interactive panel',async()=>{
  await page.evaluate(()=>{openProviders();openDataPage();setvBack();setvBack();closeSettings();openSettings()});await settle();
  const state=await page.evaluate(()=>({panel:$('setv').dataset.panel,nav:!!$('setv')._iosNav,visible:SET_PANELS.filter(id=>$(id)&&!$(id).inert&&getComputedStyle($(id)).display!=='none')}));
  assert.deepEqual(state,{panel:'homePanel',nav:false,visible:['homePanel']});
});
async function dragHeader(distance,cancel=false){
  const client=await page.context().newCDPSession(page),r=await page.locator('#setv .setbar').boundingBox(),x=r.x+r.width/2,y=r.y+12;
  await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
  for(let i=1;i<=10;i++){await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y+distance*i/10}]});await page.waitForTimeout(20)}
  if(!cancel)await page.waitForTimeout(130);
  await client.send('Input.dispatchTouchEvent',{type:cancel?'touchCancel':'touchEnd',touchPoints:[]});await client.detach();await settle();
}
await check('header drag cancellation keeps child; downward drag returns only one level',async()=>{
  await page.evaluate(()=>openProviders());await settle();await dragHeader(70,true);
  assert.equal(await page.locator('#setv').evaluate(e=>e.dataset.panel),'provListPanel');
  assert.equal(await page.locator('#setv').evaluate(e=>!!e._iosNav),false);
  await dragHeader(300);assert.equal(await page.locator('#setv').evaluate(e=>e.dataset.panel),'homePanel');
  assert.equal(await page.locator('#setv').getAttribute('aria-hidden'),'false');
});
await page.evaluate(()=>{openProviders();editProvider(null)});await settle();
await page.locator('#pvName').fill('测试服务（未保存）');await page.locator('#pvKey').fill('fixture-only');await page.locator('#pvBase').fill('https://example.test/v1');await page.locator('#pvKey').blur();
await capture('after-provider');
await check('model page rises, isolates parent, and preserves provider draft without writing',async()=>{
  const before=await page.evaluate(()=>demoState.calls.length);await page.evaluate(()=>openModelListPage());await page.waitForTimeout(60);
  const tr=await page.locator('#modelv').evaluate(e=>new DOMMatrix(getComputedStyle(e).transform).toJSON());assert.equal(tr.m41,0);assert(tr.m42>0);
  await settle();assert.equal(await page.locator('#setv').evaluate(e=>e.inert),true);
  await page.evaluate(()=>closeModelListPage());await settle();assert.equal(await page.locator('#setv').evaluate(e=>e.inert),false);
  assert.equal(await page.locator('#pvName').inputValue(),'测试服务（未保存）');assert.equal(await page.locator('#pvKey').inputValue(),'fixture-only');
  assert.equal(await page.evaluate(start=>demoState.calls.slice(start).some(c=>/^\/provider\.(save|delete)/.test(c)),before),false);
  const controls=await page.locator('#provSaveBar>button:visible').evaluateAll(es=>es.map(e=>({text:e.innerText,h:e.getBoundingClientRect().height})));
  assert(controls.every(b=>b.h>=44));assert(controls.some(b=>b.text==='测试连接'));
});
await check('closing settings while model picker is open releases both layers',async()=>{
  await page.evaluate(()=>{openModelListPage();closeSettings()});await page.waitForFunction(()=>!document.querySelector('.iosNavBusy,.iosClosing'),{},{timeout:1200});
  assert.equal(await page.locator('#modelv.on,#setv.on').count(),0);assert.equal(await page.locator('.iosNavBusy,.iosClosing').count(),0);
  await page.evaluate(()=>openSettings());await settle();
});
await check('switches keep 44-point hit areas and align at trailing edge',async()=>{
  const switches=await page.locator('#homePanel .sw:visible').evaluateAll(es=>es.map(e=>{const a=e.getBoundingClientRect(),b=e.closest('.row').getBoundingClientRect();return {w:a.width,h:a.height,gap:b.right-a.right}}));
  assert(switches.length>=3);assert(switches.every(b=>b.w>=44&&b.h>=44&&b.gap<20),JSON.stringify(switches));
});
await check('keyboard viewport retains form and action bar',async()=>{
  await page.evaluate(()=>{openProviders();editProvider(null)});await settle();
  await page.evaluate(()=>{Object.defineProperty(visualViewport,'height',{configurable:true,value:420});Object.defineProperty(visualViewport,'offsetTop',{configurable:true,value:60});visualViewport.dispatchEvent(new Event('resize'))});
  await page.locator('#pvBase').focus();await page.waitForTimeout(200);
  const r=await page.evaluate(()=>({save:$('provSaveBar').getBoundingClientRect().toJSON(),field:$('pvBase').getBoundingClientRect().toJSON(),bar:document.querySelector('#setv>.setbar').getBoundingClientRect().toJSON()}));
  assert(r.save.bottom<=480);assert(r.field.bottom<=r.save.top+1);assert(r.field.top>=r.bar.bottom-1,JSON.stringify(r));
  await capture('after-keyboard');
  await page.evaluate(()=>{document.activeElement.blur();delete visualViewport.height;delete visualViewport.offsetTop;visualViewport.dispatchEvent(new Event('resize'));closeSettings();openSettings()});await settle();
});
for(const config of [{width:430,height:932,theme:'light',lang:'zh',size:16},{width:375,height:667,theme:'dark',lang:'zh',size:22},{width:320,height:568,theme:'light',lang:'en',size:20},{width:844,height:390,theme:'dark',lang:'en',size:16}]){
  await page.setViewportSize({width:config.width,height:config.height});
  await page.evaluate(c=>{setLang(c.lang);document.documentElement.setAttribute('data-theme',c.theme);document.documentElement.style.fontSize=c.size+'px';['setv','modelv'].forEach(id=>$(id).style.fontSize=c.size+'px');closeSettings();openSettings()},config);await settle();
  await capture(`matrix-${config.width}-${config.theme}-${config.lang}-home`);
  for(const route of ['provListPanel','dataPanel','statsPanel','filesPanel','memPanel','integrationsPanel']){
    await page.evaluate(route=>route==='integrationsPanel'?openIntegrations():setNav(route,({provListPanel:t('providersModels'),dataPanel:t('storageSpace'),statsPanel:t('stats'),filesPanel:t('genFiles'),memPanel:t('memPanelTitle')})[route]),route);await settle();
    const dims=await page.locator('#setv>.setbody').evaluate(e=>({width:e.clientWidth,scrollWidth:e.scrollWidth}));assert(dims.scrollWidth<=dims.width+1,JSON.stringify({route,config,dims}));
    if(config.width===375)await capture(`matrix-${config.width}-${route}`);
    await page.evaluate(()=>setvBack());await settle();
  }
}
await page.setViewportSize({width:430,height:932});
await page.evaluate(()=>{setLang('zh');document.documentElement.setAttribute('data-theme','light');document.documentElement.style.fontSize='16px';$('setv').style.fontSize='17px';closeSettings();openSettings()});await settle();
await check('appearance and failover settings use the same bottom edge and dismiss cleanly',async()=>{
  await page.evaluate(()=>providers=[{id:'fixture',name:'Fixture provider',apikey:'fixture-only',apibase:'https://example.test/v1',model:'fixture-model',models:['fixture-model'],type:'oai',enabled:true}]);
  for(const [fn,id] of [['openThemeSheet','themeSheet'],['openFailoverSheet','failoverSheet']]){
    await page.evaluate(fn=>window[fn](),fn);await page.waitForTimeout(60);assert.equal(await page.locator('#'+id).getAttribute('aria-hidden'),'false');
    assert(await page.locator('#'+id).evaluate(e=>new DOMMatrix(getComputedStyle(e).transform).m42>=0));
    await settle();await capture('after-'+id);await page.evaluate(()=>closeSheets());await settle();
    assert.equal(await page.locator('#'+id).getAttribute('aria-hidden'),'true');
  }
});
await require('./file_preview_checks.cjs')({page,check,capture,settle});
await require('./privacy_stats_checks.cjs')({page,check,capture,settle});
await require('./model_issue_checks.cjs')({page,check,capture,settle});
await require('./provider_editor_checks.cjs')({page,check,capture,settle});
await check('reduced motion keeps navigation correct with no pending transitions',async()=>{
  await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>{openProviders();openDataPage();setvBack();setvBack()});
  assert.equal(await page.locator('#setv').evaluate(e=>e.dataset.panel),'homePanel');assert.equal(await page.locator('.iosNavBusy').count(),0);
});
await check('the first-run hint appears in words, once the iOS strings are loaded',async()=>{
  const first=await browser.newPage({viewport:{width:390,height:844}});await first.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());
  await first.addInitScript({content:boot.replace("'ga.ios.destination','computer'","'ga.ios.destination','assistant'")});
  await first.goto('http://127.0.0.1:'+server.address().port);await first.waitForTimeout(400);
  assert.equal(await first.locator('.iosHint').textContent(),'点这里开始新对话');await first.close();
});
await check('Android does not load iOS layout or route effects',async()=>{
  const other=await browser.newPage({viewport:{width:390,height:844}});await other.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());await other.goto('http://127.0.0.1:'+server.address().port);await other.waitForTimeout(300);
  assert.equal(await other.locator('#iosBoardSetup,#iosSetvDone').count(),0);assert.equal(await other.locator('html').evaluate(e=>e.classList.contains('iosApp')),false);await other.close();
});
assert.deepEqual(errors,[]);fs.writeFileSync(out+'/ui-results.json',JSON.stringify({results,errors},null,2));
console.log(JSON.stringify({checks:results.filter(r=>r.check).length,screenshots:results.filter(r=>r.capture).length,errors}));await browser.close();server.close();
})().catch(e=>{console.error(e);process.exit(1)});
