// Actual WebUI and iOS bridge, with two isolated desktop fixtures.
const fs=require('fs'),http=require('http'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'../..'),web=root+'/app/src/main/assets/ga_runtime/webui';
const out=process.env.IOS_PCLINK_ARTIFACTS||fs.mkdtempSync(path.join(require('os').tmpdir(),'gagent-pclink-'));
fs.mkdirSync(out,{recursive:true});
const boot=`${fs.readFileSync(web+'/assets/shim.js','utf8')}
const demoGA=window.GA;delete window.GA;
window.fixture={calls:[],hubs:['Mac A','Mac B'],created:[],sent:[],offline:[],delayed:false,jobs:{}};
window.prompt=(sentinel,payload)=>{const q=JSON.parse(payload),cmd=q.args[0],s=fixture;
 if(q.kind==='native'){if(q.fn==='isDark')return 'false';if(q.fn==='boardStatus')return '{}';return demoGA[q.fn]?String(demoGA[q.fn](...q.args)||''):''}
 if(q.fn==='ready')return 'ok';if(q.fn==='caps')return '{}';
 if(q.fn==='poll')return JSON.stringify({running:false,status:'就绪',gen:1,nsteps:0,steps:[],hist:[]});
 if(q.fn==='send'){
  s.calls.push(cmd);
  if(cmd==='/ios.consent.status')return JSON.stringify({ok:true,pcAccepted:true,accepted:true,needsRefresh:false,receivers:[]});
  if(cmd.startsWith('/pclink.status')||cmd.startsWith('/pclink.resume'))return JSON.stringify({paired:true,connected:true});
  if(cmd==='/jobresult create')return JSON.stringify(s.createPaused?{pending:true}:{result:JSON.stringify({ok:1,name:s.createdName})});
  if(cmd==='/jobresult put')return JSON.stringify(s.delayed?{pending:true}:{result:'{"ok":1}'});
  if(cmd.includes('/model_settings')){
   if(s.legacyModels)return JSON.stringify({error:'unsupported',status:404});
   const data={selected:'a',revision:s.modelRevision||'r1',busy:false,profiles:[{id:'a',name:'Work provider',models:['reasoning-model'],reasoning:{value:'high',choices:['low','medium','high']}},{id:'b',name:'Second provider',models:['fast-model'],reasoning:{value:'default',choices:[]}}]};
   if(cmd.includes(' POST ')){s.modelChange={path:cmd.split(' ')[2],body:JSON.parse(cmd.split(' ').slice(3).join(' '))};if(s.modelChange.body.revision!==data.revision)return JSON.stringify({error:'电脑配置已更新，请重新选择',code:'conflict',status:409});return JSON.stringify({ok:1,...data})}
   return JSON.stringify(data);
  }
  if(cmd.includes('/llms'))return JSON.stringify({items:['Legacy provider'],cur:0});
  if(cmd.includes('/api/hubs'))return JSON.stringify(s.hubs);
  if(cmd.startsWith('/pclink.api POST /api/sessions ')){
   const body=JSON.parse(cmd.split(' ').slice(3).join(' '));s.created.push(body);
   if(s.createPaused)return JSON.stringify({job:'create'});
   return JSON.stringify({ok:1,name:'same-session@'+body.hub});
  }
  if(cmd.includes('/api/peers'))return JSON.stringify(s.hubs.filter(h=>!s.offline.includes(h)).map(h=>({name:'same-session@'+h,hub:h,title:'同名任务',caps:['get','put']})).concat(s.createdName&&!s.createPaused?[{name:s.createdName,hub:'Mac B',caps:['get','put']}]:[]).concat([{name:'history.unused',caps:['history-v1']}]));
  if(cmd.includes('/put ')){
   const url=decodeURIComponent(cmd.split(' ')[2]),hub=url.split('@')[1].split('/')[0];
   s.sent.push({hub,peer:url.split('/')[2],body:JSON.parse(cmd.split(' ').slice(3).join(' '))});
   return JSON.stringify(s.delayed?{job:'put'}:{ok:1});
  }
  if(cmd.includes('/messages'))return JSON.stringify({tasks:[],title:'同名任务',sig:'empty',run:false});
  if(['/config','/storageinfo'].includes(cmd)||/^\\/(kv\\.|lang|clear)/.test(cmd))return demoGA.send(cmd);
  return '{}';
 }
 return demoGA[q.fn]?demoGA[q.fn](...q.args):'';
};
localStorage.setItem('ga.lang','"zh"');localStorage.setItem('ga.authSkipped','true');localStorage.setItem('ga.privacyConsent','true');localStorage.setItem('ga.theme','"light"');
${fs.readFileSync(root+'/ios/GAgent/ios_bridge.js','utf8')}`;

(async()=>{
 const results=[],errors=[];
 const server=http.createServer((req,res)=>{const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file))}catch(e){res.statusCode=404;res.end('')}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
 try{
  const page=await browser.newPage({viewport:{width:430,height:932},isMobile:true,hasTouch:true,deviceScaleFactor:2});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());
  await page.addInitScript({content:boot});await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForTimeout(500);await page.evaluate(()=>PCLINK.openView());
  const settle=()=>page.waitForTimeout(600);
  async function check(name,fn){try{await fn();results.push({name,passed:true})}catch(e){console.error(name,await page.evaluate(()=>({title:document.getElementById('pcHdTitle')?.title,created:fixture.created,calls:fixture.calls.slice(-25)})));throw e}}
  await check('initial poll shows live sessions without creating one first',async()=>{
   await page.waitForFunction(()=>document.querySelectorAll('#pcSideList .pcRow').length>=2);
   assert.equal(await page.locator('#pcSideList .pcRow').count(),2,await page.locator('#pcSideList').innerText());
   assert.equal(await page.locator('#pcSideList').innerText().then(s=>s.includes('Mac A')&&s.includes('Mac B')),true);
   assert.equal(await page.locator('#pcMsgs .pcBootHero').count(),0);
  });
  await check('two computers require an explicit destination before creating',async()=>{
   await page.locator('#pcNewBtn').click();await page.locator('#pcSheetWrap').waitFor();
   assert.equal(await page.evaluate(()=>fixture.created.length),0);
   await page.getByRole('button',{name:'Mac B',exact:true}).click();
   await page.waitForFunction(()=>fixture.created.length===1);await settle();
   assert.deepEqual(await page.evaluate(()=>fixture.created),[{hub:'Mac B'}]);
   assert.match(await page.locator('#pcHdSub').innerText(),/Mac B/);
  });
  await check('message goes to the selected computer exactly once',async()=>{
   await page.locator('#pcIn').fill('路由验收 B');await page.locator('#pcBtn').click();await settle();
   assert.equal(await page.evaluate(()=>fixture.sent.length),1);
   assert.equal(await page.evaluate(()=>fixture.sent[0].hub),'Mac B');
   assert.equal(await page.evaluate(()=>fixture.sent[0].body.text),'路由验收 B');
  });
  await check('late response cannot clear another computers draft',async()=>{
   await page.evaluate(()=>fixture.delayed=true);await page.locator('#pcIn').fill('迟到的 B 请求');await page.locator('#pcBtn').click();
   await page.waitForFunction(()=>fixture.sent.length===2);
   await page.locator('#pcNewBtn').click();await page.getByRole('button',{name:'Mac A',exact:true}).click();await settle();
   await page.locator('#pcIn').fill('A 的草稿');await page.evaluate(()=>fixture.delayed=false);await settle();
   assert.equal(await page.locator('#pcIn').inputValue(),'A 的草稿');
   assert.match(await page.locator('#pcHdSub').innerText(),/Mac A/);
   await page.locator('#pcBtn').click();await settle();
   assert.deepEqual(await page.evaluate(()=>fixture.sent.map(x=>x.hub)),['Mac B','Mac B','Mac A']);
  });
  await check('background peer changes cannot steal a newly created session',async()=>{
   await page.evaluate(()=>{fixture.createPaused=true;fixture.createdName='new-session@Mac B'});
   await page.locator('#pcNewBtn').click();await page.getByRole('button',{name:'Mac B',exact:true}).click();
   await page.waitForFunction(()=>fixture.created.length===3);
   assert.equal(await page.locator('#pcBtn').isDisabled(),true);
   await page.evaluate(()=>fixture.offline=['Mac A']);
   await page.waitForTimeout(7000); // existing poll observes that the selected old session disappeared
   await page.evaluate(()=>fixture.createPaused=false);
   await page.waitForFunction(()=>document.getElementById('pcHdTitle').title==='new-session@Mac B',null,{timeout:5000});
   await page.evaluate(()=>fixture.offline=[]);
   await page.locator('#pcIn').fill('新会话');await page.locator('#pcBtn').click();await settle();
   assert.equal(await page.evaluate(()=>fixture.sent.at(-1).peer),'new-session@Mac B');
  });
  await check('polling does not discard a pending send receipt in the same session',async()=>{
   await page.evaluate(()=>fixture.delayed=true);
   await page.locator('#pcIn').fill('等待回执');await page.locator('#pcBtn').click();
   await page.waitForTimeout(1700);await page.evaluate(()=>fixture.delayed=false);
   await page.waitForFunction(()=>document.getElementById('pcIn').value==='');
  });
  await check('voice is bound even when the computer view opened before voice.js',async()=>{
   assert.equal(await page.locator('#pcVoiceBtn').isVisible(),true);
   assert.equal(await page.locator('#pcVoiceBtn').evaluate(e=>e.classList.contains('vHold')),true);
  });
  await check('computer model sheet selects remote configuration with scoped reasoning',async()=>{
   await page.locator('#pcModelBtn').click();await page.locator('.pcModelOption').first().waitFor();
   assert.equal(await page.locator('.pcModelOption').count(),2);
   await page.locator('#pcReasoning').selectOption('low');
   await page.waitForTimeout(400);await page.screenshot({path:out+'/computer-models.png'});
   await page.locator('.pcModelSave').click();await settle();
   assert.deepEqual(await page.evaluate(()=>fixture.modelChange.body),{revision:'r1',profile:'a',reasoning:'low'});
   assert.match(await page.evaluate(()=>decodeURIComponent(fixture.modelChange.path)),/new-session@Mac B/);
   await page.locator('#pcModelBtn').click();await page.locator('.pcModelOption').last().click();
   assert.equal(await page.locator('#pcReasoning').isDisabled(),true);
   await page.locator('.pcModelDone').click();await settle();
  });
  await check('older computers retain channel selection without fake reasoning controls',async()=>{
   await page.evaluate(()=>fixture.legacyModels=true);await page.locator('#pcModelBtn').click();
   await page.getByRole('button',{name:'Legacy provider'}).waitFor();
   assert.equal(await page.locator('.pcReasoning').isVisible(),false);
   await page.locator('.pcModelDone').click();await page.evaluate(()=>fixture.legacyModels=false);await settle();
  });
  await check('external configuration changes refresh the sheet without replaying a stale write',async()=>{
   await page.locator('#pcModelBtn').click();await page.locator('.pcModelOption').first().waitFor();
   await page.evaluate(()=>fixture.modelRevision='r2');await page.locator('.pcModelSave').click();await settle();
   assert.equal(await page.locator('.pcModelOption').count(),2);
   assert.equal(await page.evaluate(()=>fixture.modelChange.body.revision),'r1');
   await page.locator('.pcModelSave').click();await settle();
   assert.equal(await page.evaluate(()=>fixture.modelChange.body.revision),'r2');
  });
  await check('no third-party history UI, discovery, import or continuation',async()=>{
   await page.evaluate(()=>{PCLINK.closeView();openSettings()});await settle();
   assert.equal(await page.locator('#pcHistoryEntry,#pcHistoryPanel,#pcHistoryContinue,#pcSideHistory').count(),0);
   assert.equal(await page.evaluate(()=>!!window.PCHistory||!!window.PCHistoryLink),false);
   assert.equal(await page.evaluate(()=>fixture.calls.some(c=>/pclink.history|catalog|sessions\/continue/.test(c))),false);
   await page.evaluate(()=>{closeSettings();PCLINK.openView()});await settle();
   assert.equal(await page.locator('#pcSideList').innerText().then(s=>s.includes('history.unused')),false);
  });
  await check('both sidebars keep compact footers inside visible viewport',async()=>{
   for(const c of [{width:430,height:932,theme:'light',size:17},{width:320,height:568,theme:'dark',size:22}]){
    await page.setViewportSize(c);await page.evaluate(c=>{document.documentElement.dataset.theme=c.theme;document.documentElement.style.fontSize=c.size+'px'},c);
    for(const pc of [false,true]){
     await page.evaluate(pc=>{if(pc){PCLINK.openView();document.getElementById('pcView').classList.add('side')}else{PCLINK.closeView();openDrawer()}},pc);await settle();
     const area=pc?'#pcSide':'#drawer';
     const m=await page.locator(area+' .dwUserBar').evaluate(e=>{const r=e.getBoundingClientRect(),a=e.querySelector('.dwUser').getBoundingClientRect(),b=e.querySelector('[data-i18n-aria="settings"]').getBoundingClientRect();return {bar:r.toJSON(),avatar:a.toJSON(),settings:b.toJSON(),vh:visualViewport.height}});
     assert(m.bar.bottom<=m.vh+1);assert(m.bar.height<=80);assert(m.settings.height>=44);assert(m.avatar.height>=44);
     assert(Math.abs(m.settings.y+m.settings.height/2-m.avatar.y-m.avatar.height/2)<1);
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
     await page.screenshot({path:out+'/'+(pc?'pc':'local')+'-drawer-'+c.width+'.png'});
     await page.evaluate(()=>{closeDrawer();document.getElementById('pcView').classList.remove('side')});
    }
   }
  });
  assert.deepEqual(errors,[]);fs.writeFileSync(out+'/result.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results));
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
