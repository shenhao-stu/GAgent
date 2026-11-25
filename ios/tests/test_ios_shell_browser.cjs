// Real WebUI + fixture bridge. Synthetic visualViewport models keyboard geometry;
// device keyboard timing is deliberately not claimed by this browser regression.
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../..'),web=root+'/app/src/main/assets/ga_runtime/webui';
const out=process.env.IOS_SHELL_ARTIFACTS||fs.mkdtempSync('/tmp/gagent-shell-');
fs.mkdirSync(out,{recursive:true});
const boot=`${fs.readFileSync(web+'/assets/shim.js','utf8')}
const demoGA=window.GA;delete window.GA;
window.fixture={calls:[],slow:false};
window.prompt=(sentinel,payload)=>{const q=JSON.parse(payload),cmd=q.args[0];
 if(q.kind==='native'){if(q.fn==='isDark')return 'false';if(q.fn==='boardStatus')return '{}';return demoGA[q.fn]?String(demoGA[q.fn](...q.args)||''):''}
 if(q.fn==='ready')return 'ok';if(q.fn==='caps')return '{}';
 if(q.fn==='poll')return JSON.stringify({running:false,status:'就绪',gen:1,nsteps:0,steps:[],hist:[]});
 if(q.fn==='send'){
  fixture.calls.push({cmd,at:performance.now()});
  if(cmd==='/ios.consent.status')return '{"ok":true,"pcAccepted":true,"accepted":true,"needsRefresh":false,"receivers":[]}';
  if(cmd.startsWith('/pclink.')){
   if(fixture.slow){const end=performance.now()+70;while(performance.now()<end){}}
   if(cmd.startsWith('/pclink.status')||cmd.startsWith('/pclink.resume'))return '{"paired":true,"connected":true}';
   if(cmd.includes('/api/hubs'))return '["Fixture Mac"]';
   if(cmd.includes('/api/peers'))return '[{"name":"shell@Fixture Mac","title":"测试会话","caps":["get","put"]}]';
   if(cmd.includes('/messages'))return JSON.stringify({tasks:Array.from({length:fixture.messageCount||0},(_,i)=>({i,input:'Remote message '+i+' — '.repeat(80),steps:[]})),title:'测试会话',sig:String(fixture.messageCount||0),run:false});
   return '{}';
  }
  if(['/config','/storageinfo'].includes(cmd)||/^\\/(kv\\.|lang|clear)/.test(cmd))return demoGA.send(cmd);
  return '{}';
 }
 return demoGA[q.fn]?demoGA[q.fn](...q.args):'';
};
for(const [k,v] of Object.entries({'ga.lang':'"zh"','ga.theme':'"light"','ga.authSkipped':'true','ga.privacyConsent':'true'}))if(!localStorage.getItem(k))localStorage.setItem(k,v);
${fs.readFileSync(root+'/ios/GAgent/ios_bridge.js','utf8')}`;
module.exports={boot};
if(require.main===module)(async()=>{
 const results=[],errors=[];
 const server=http.createServer((req,res)=>{const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file))}catch{res.statusCode=404;res.end()}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
 try{
  const page=await browser.newPage({viewport:{width:430,height:932},isMobile:true,hasTouch:true,deviceScaleFactor:2});
  page.setDefaultTimeout(4000);
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());
  await page.addInitScript({content:boot});await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForFunction(()=>window.GAIOS);await page.waitForTimeout(600);
  const settle=()=>page.waitForTimeout(450);
  const rect=s=>page.locator(s).evaluate(e=>{const r=e.getBoundingClientRect(),top=visualViewport.offsetTop;return {x:r.x,y:r.y-top,width:r.width,height:r.height,bottom:r.bottom-top}});
  const keyboard=async(h,top=0)=>{await page.evaluate(({h,top})=>{
   Object.defineProperties(visualViewport,{height:{configurable:true,get:()=>h},offsetTop:{configurable:true,get:()=>top}});
   visualViewport.dispatchEvent(new Event('resize'));visualViewport.dispatchEvent(new Event('scroll'));
  },{h,top});await settle()};
  const near=(a,b,msg)=>assert(Math.abs(a-b)<1,`${msg}: ${a} vs ${b}`);
  async function check(name,fn){try{const metrics=await fn();results.push({name,passed:true,metrics})}catch(e){results.push({name,passed:false,error:e.message});console.error(name,e.message)}}
  await check('phone/computer headers occupy identical geometry',async()=>{
   assert(await page.locator('#hdrMoreBtn').isVisible(),'new conversation stays available on the phone home');
   const local=await rect('#hdr .gaLogo'),localNew=await rect('#hdrMoreBtn');await page.evaluate(()=>PCLINK.openView());await settle();
   const pc=await rect('.pcHd .gaLogo'),pcNew=await rect('#pcNewBtn');await page.evaluate(()=>PCLINK.closeView());await settle();
   for(const k of ['x','y','width','height']){near(local[k],pc[k],k);near(localNew[k],pcNew[k],'new conversation '+k)}
   await page.locator('#hdrMoreBtn').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'in');
   await page.locator('#in').blur();
   await page.evaluate(()=>renderConvo({id:'header-existing',title:'已有会话',msgs:[{role:'user',text:'Existing conversation'}]}));await settle();
   assert(await page.locator('#hdrMoreBtn').isVisible());await page.locator('#hdrMoreBtn').click();
   assert(await page.locator('#empty').isVisible());assert.equal(await page.evaluate(()=>curConvo),null);
   assert(await page.locator('#hdrMoreBtn').isVisible());await page.locator('#in').blur();await settle();
   return {local,pc,localNew,pcNew};
  });
  await check('computer home shares phone typography and suggestion grid without sending',async()=>{
   const phone=await rect('#empty h2');
   const style=s=>page.locator(s).first().evaluate(e=>{const c=getComputedStyle(e);return [c.fontSize,c.fontWeight,c.lineHeight,c.borderRadius,c.backgroundColor]});
   const phoneTitle=await style('#empty h2'),phoneCard=await style('#heroChips button');
   await page.evaluate(()=>PCLINK.openView());await page.waitForSelector('.pcStart');await settle();
   const computer=await rect('.pcStart h2');
   assert.deepEqual(await style('.pcStart h2'),phoneTitle);near(phone.y,computer.y,'matching home title y');
   assert.deepEqual(await style('.pcStarterList button'),phoneCard);
   const cards=await page.locator('.pcStarterList button').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().toJSON()));
   assert.equal(cards.length,4);near(cards[0].y,cards[1].y,'first card row');near(cards[2].y,cards[3].y,'second card row');assert(cards.every(r=>r.height>=48));
   await page.screenshot({path:out+'/computer-home-matched.png'});
   await page.evaluate(()=>fixture.calls=[]);await page.locator('.pcStarterList button').last().click();await keyboard(518);
   near((await rect('.pcStart h2')).y,computer.y,'computer home keyboard');await keyboard(864);near((await rect('.pcStart h2')).y,computer.y,'computer accessory frame');
   assert((await page.locator('#pcIn').inputValue()).includes('整理文件'));assert.equal(await page.evaluate(()=>fixture.calls.some(c=>c.cmd.includes('/put'))),false);
   await page.locator('#pcIn').fill('');await page.locator('#pcIn').blur();await keyboard(932);
   await page.locator('.iosComputerCard').click();assert(await page.evaluate(()=>document.getElementById('pcView').classList.contains('side')));
   await page.evaluate(()=>{document.getElementById('pcView').classList.remove('side');PCLINK.closeView()});await settle();
   return {phone,computer,cards};
  });
  await check('keyboard keeps the local hero and header stable without removing suggestions',async()=>{
   await page.evaluate(()=>{PCLINK.closeView();window.savedHero=document.querySelector('#empty .heroCore')});await settle();
   const before=await rect('#empty h2'),logo=await rect('#hdr .gaLogo');
   await page.locator('#in').focus();await keyboard(580,24);
   const after=await rect('#empty h2'),focusedLogo=await rect('#hdr .gaLogo');
   await page.screenshot({path:out+'/local-keyboard.png'});
   const same=await page.evaluate(()=>savedHero===document.querySelector('#empty .heroCore'));
   const chips=await page.locator('#heroChips').isVisible();
   const composer=await rect('#comp');
   await page.locator('#in').blur();await keyboard(932);
   assert(same);assert(chips,'suggestions should stay mounted and visible in the scroll area');
   near(before.y,after.y,'hero y');near(before.height,after.height,'hero text size');near(logo.y,focusedLogo.y,'logo y');near(composer.bottom,580,'composer bottom');
   return {before,after,logo,focusedLogo,composer};
  });
  await check('computer keyboard resizes the reading area exactly once',async()=>{
   await page.evaluate(()=>PCLINK.openView());await settle();const logo=await rect('.pcHd .gaLogo');
   await page.locator('#pcIn').fill('电脑草稿');await keyboard(580,24);
   const header=await rect('.pcHd .gaLogo'),composer=await rect('#pcInBar'),messages=await rect('#pcMsgs');
   await page.screenshot({path:out+'/computer-keyboard.png'});
   await page.locator('#pcIn').blur();await keyboard(932);
   near(logo.y,header.y,'logo y');near(composer.bottom,580,'composer bottom');assert(messages.bottom<=composer.y+1,'messages must end above the composer');
   return {logo,header,composer,messages};
  });
  await check('WebKit resizing both viewports still keeps the local hero stable',async()=>{
   await page.evaluate(()=>PCLINK.closeView());await settle();
   const before=await rect('#empty h2');await page.locator('#in').focus();
   await page.evaluate(()=>{window.originalInnerHeight=Object.getOwnPropertyDescriptor(window,'innerHeight');Object.defineProperty(window,'innerHeight',{configurable:true,value:580})});
   await keyboard(580);const after=await rect('#empty h2');
   const detected=await page.evaluate(()=>document.documentElement.classList.contains('iosKeyboard'));
   await page.locator('#in').blur();await page.evaluate(()=>Object.defineProperty(window,'innerHeight',originalInnerHeight));await keyboard(932);
   assert(detected);near(before.y,after.y,'hero y when innerHeight also shrinks');return {before,after};
  });
  await check('keyboard accessory-only frames retain the resting hero geometry',async()=>{
   await page.evaluate(()=>PCLINK.closeView());await settle();
   const before=await rect('#empty h2');await page.locator('#in').focus();await keyboard(518);
   await keyboard(864);const accessory=await rect('#empty h2');
   const retained=await page.evaluate(()=>document.documentElement.classList.contains('iosKeyboard'));
   await keyboard(518);const restored=await rect('#empty h2');
   await page.locator('#in').blur();await keyboard(864);const dismissing=await rect('#empty h2');
   await keyboard(932);
   assert(retained,'accessory-only frames must not reset the resting keyboard geometry');
   for(const [name,r] of Object.entries({accessory,restored,dismissing}))near(before.y,r.y,name+' hero y');
   return {before,accessory,restored,dismissing};
  });
  await check('large-text home keeps user scrolling through idle polls and resume',async()=>{
   await page.evaluate(()=>{PCLINK.closeView();newConversation();inp.blur();document.documentElement.style.fontSize='53px'});await settle();
   try{
    const area=await rect('#chat');await page.mouse.move(area.x+area.width/2,area.y+area.height/2);
    await page.mouse.wheel(0,220);await page.waitForTimeout(120);
    const reading=await page.evaluate(()=>chat.scrollTop);assert(reading>0,'large-text home can be scrolled');
    await page.evaluate(()=>{poll();pinBottom()});await settle();
    near(await page.evaluate(()=>chat.scrollTop),reading,'home reading after idle poll and resume');
    await page.evaluate(()=>{newConversation();inp.blur()});await settle();
    near(await page.evaluate(()=>chat.scrollTop),0,'new home starts at the top');
    await page.evaluate(()=>{GA.platform='android';chat.scrollTop=0;scroll(true)});
    near(await page.evaluate(()=>chat.scrollHeight-chat.clientHeight-chat.scrollTop),0,'Android scroll keeps its existing bottom behavior');
    await page.evaluate(()=>{chat.scrollTop=0;pinBottom()});await page.waitForTimeout(500);
    near(await page.evaluate(()=>chat.scrollHeight-chat.clientHeight-chat.scrollTop),0,'Android pin keeps its existing bottom behavior');
    return {rootFont:53,reading};
   }finally{await page.evaluate(()=>{GA.platform='ios';document.documentElement.style.removeProperty('font-size');newConversation();inp.blur()});await settle()}
  });
  await check('view switch never moves the header and paints before slow bridge refresh',async()=>{
   await page.evaluate(()=>PCLINK.closeView());await settle();
   const samples=await page.evaluate(async()=>{
    fixture.slow=true;fixture.calls=[];const frames=[],start=performance.now();
    PCLINK.openView();const returned=performance.now()-start;
    await new Promise(resolve=>{const tick=()=>{const e=document.querySelector('.pcHd .gaLogo'),r=e.getBoundingClientRect();frames.push({at:performance.now()-start,y:r.y,transform:getComputedStyle(document.getElementById('pcView')).transform});if(performance.now()-start<350)requestAnimationFrame(tick);else resolve()};requestAnimationFrame(tick)});
    fixture.slow=false;return {returned,frames};
   });
   assert(samples.returned<50,`synchronous navigation blocked ${samples.returned.toFixed(0)}ms`);
   assert(samples.frames.every(f=>f.transform==='none'),'header must not travel with an entering page');return samples;
  });
  await check('switching preserves drafts and mounted nodes',async()=>{
   await page.evaluate(()=>{window.savedPC=document.querySelector('#pcMsgs').firstElementChild;PCLINK.closeView()});await settle();
   await page.locator('#in').fill('本机草稿');
   await page.evaluate(()=>{window.savedLocal=document.querySelector('#empty');PCLINK.openView()});await settle();
   assert.equal(await page.locator('#pcIn').inputValue(),'电脑草稿');
   assert(await page.evaluate(()=>savedPC===document.querySelector('#pcMsgs').firstElementChild));
   await page.evaluate(()=>PCLINK.closeView());await settle();
   assert.equal(await page.locator('#in').inputValue(),'本机草稿');assert(await page.evaluate(()=>savedLocal===document.querySelector('#empty')));
  });
  await check('rapid switches cancel the obsolete foreground refresh',async()=>{
   await page.evaluate(()=>{PCLINK.closeView();fixture.calls=[];PCLINK.openView();PCLINK.closeView()});await settle();
   assert.equal(await page.evaluate(()=>document.body.dataset.iosPage),'assistant');
   assert.equal(await page.evaluate(()=>fixture.calls.some(c=>c.cmd.includes('/messages'))),false);
   await page.evaluate(()=>{PCLINK.openView();PCLINK.closeView();PCLINK.openView()});await settle();
   assert.equal(await page.evaluate(()=>document.body.dataset.iosPage),'computer');
   assert.equal(await page.evaluate(()=>document.getElementById('pcView').inert),false);
   assert.equal(await page.evaluate(()=>document.getElementById('app').inert),true);
  });
  await check('long conversation reading position survives keyboard, switching and theme',async()=>{
   await page.evaluate(()=>{PCLINK.closeView();renderConvo({id:'shell-reading',title:'阅读中的会话',msgs:Array.from({length:24},(_,i)=>({role:'user',text:'第 '+i+' 条消息：保持阅读位置。'.repeat(12)}))})});await settle();
   await page.evaluate(()=>{chat.scrollTop=400;stick=false;pinned=false;window.savedMessage=chat.firstElementChild});
   await page.locator('#in').focus();await keyboard(580,24);
   near(await page.evaluate(()=>chat.scrollTop),400,'reading while keyboard opens');
   await page.locator('#in').blur();await keyboard(932);
   await page.evaluate(()=>PCLINK.openView());await settle();await page.evaluate(()=>PCLINK.closeView());await settle();
   near(await page.evaluate(()=>chat.scrollTop),400,'reading after returning');
   await page.evaluate(()=>openDrawer());await settle();await page.locator('#drawer .iosSidebarTheme').click();
   assert(await page.evaluate(()=>savedMessage===chat.firstElementChild),'theme must not recreate messages');
   near(await page.evaluate(()=>chat.scrollTop),400,'reading after theme change');
   await page.locator('#drawer .iosSidebarTheme').click();
   await page.locator('#drawer .iosSidebarLanguage').click();await settle();
   near(await page.evaluate(()=>chat.scrollTop),400,'reading after language change');
   await page.locator('#drawer .iosSidebarLanguage').click();await page.evaluate(()=>closeDrawer());
  });
  await check('remote reading position and follow-latest survive keyboard resize',async()=>{
   await page.evaluate(()=>{fixture.messageCount=20;PCLINK.openView()});
   await page.waitForFunction(()=>document.querySelectorAll('#pcMsgs .pcTask').length===20);await settle();
   await page.evaluate(()=>{const b=document.getElementById('pcMsgs');b.dispatchEvent(new WheelEvent('wheel',{deltaY:-100,bubbles:true}));b.scrollTop=400});await settle();
   await page.locator('#pcIn').focus();await keyboard(580);
   near(await page.locator('#pcMsgs').evaluate(e=>e.scrollTop),400,'remote reading offset');
   await page.evaluate(()=>{const b=document.getElementById('pcMsgs');b.scrollTop=b.scrollHeight;b._pcStick=true});
   await page.locator('#pcIn').blur();await keyboard(932);
   near(await page.locator('#pcMsgs').evaluate(e=>e.scrollHeight-e.scrollTop-e.clientHeight),0,'remote latest after keyboard closes');
   await page.locator('#pcIn').focus();await keyboard(580);
   near(await page.locator('#pcMsgs').evaluate(e=>e.scrollHeight-e.scrollTop-e.clientHeight),0,'remote latest after keyboard opens');
   await page.locator('#pcIn').blur();await keyboard(932);await page.evaluate(()=>{fixture.messageCount=0;PCLINK.closeView()});
  });
  await check('both drawers provide language and appearance actions that persist',async()=>{
   for(const pc of [false,true]){
    await page.evaluate(pc=>{if(pc){PCLINK.openView();document.getElementById('pcView').classList.add('side')}else{PCLINK.closeView();openDrawer()}},pc);await settle();
    const side=pc?'#pcSide':'#drawer';
    await page.locator(side+' .iosSidebarLanguage').click();assert.equal(await page.evaluate(()=>lang),pc?'zh':'en');
    await page.locator(side+' .iosSidebarTheme').click();assert.equal(await page.evaluate(()=>theme),pc?'light':'dark');
    await page.screenshot({path:out+'/'+(pc?'pc':'local')+'-preferences.png'});
    await page.evaluate(()=>{closeDrawer();document.getElementById('pcView').classList.remove('side')});
   }
   await page.evaluate(()=>{PCLINK.closeView();openDrawer()});await settle();
   await page.locator('#drawer .iosSidebarLanguage').click();await page.locator('#drawer .iosSidebarTheme').click();
   await page.reload();await page.waitForFunction(()=>window.GAIOS);assert.equal(await page.evaluate(()=>lang),'en');assert.equal(await page.evaluate(()=>theme),'dark');
  });
  await check('small screen / large text retains 44px targets and footer safety',async()=>{
   await page.setViewportSize({width:320,height:568});await page.evaluate(()=>{document.documentElement.style.fontSize='22px';setLang('en')});await keyboard(568);
   for(const pc of [false,true]){
    await page.evaluate(pc=>{if(pc){PCLINK.openView();document.getElementById('pcView').classList.add('side')}else{PCLINK.closeView();openDrawer()}},pc);await settle();
    const side=pc?'#pcSide':'#drawer';
    const buttons=await page.locator(side+' .dwUserBar').evaluate(e=>[e.querySelector('.iosSidebarLanguage'),e.querySelector('.iosSidebarTheme'),e.querySelector('.dwIcon[data-i18n-aria="settings"]')].map(e=>e.getBoundingClientRect().toJSON()));
    assert.equal(buttons.length,3);assert(buttons.every(r=>r.height>=44&&r.width>=44&&r.bottom<=568));
    near(buttons[0].y,buttons[2].y,'language beside settings');near(buttons[1].y,buttons[2].y,'appearance beside settings');
    assert(buttons[0].right<=buttons[1].x&&buttons[1].right<=buttons[2].x,'language and appearance must sit left of settings');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:out+'/'+(pc?'pc':'local')+'-small.png'});
    await page.evaluate(()=>{closeDrawer();document.getElementById('pcView').classList.remove('side')});
   }
  });
  await check('reduce motion disables destination animation',async()=>{
   await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>PCLINK.openView());
   assert(await page.locator('#pcView').evaluate(e=>getComputedStyle(e).transitionDuration.split(',').every(s=>parseFloat(s)<.001)));
  });
  results.push({name:'no uncaught browser errors',passed:errors.length===0,errors});
  fs.writeFileSync(out+'/result.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results));
  if(results.some(r=>!r.passed))process.exitCode=1;
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
