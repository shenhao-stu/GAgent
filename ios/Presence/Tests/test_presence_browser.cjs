// Real chat CSS and Presence injection: touch targets, layout and conversation ownership.
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {boot}=require('../../tests/test_ios_shell_browser.cjs');
const root=path.resolve(__dirname,'../../..'),web=root+'/app/src/main/assets/ga_runtime/webui';
const out=process.env.PRESENCE_BROWSER_ARTIFACTS||fs.mkdtempSync('/tmp/gagent-presence-');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const errors=[],results=[];
 const server=http.createServer((req,res)=>{const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);try{
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
 }catch{res.statusCode=404;res.end()}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());
  await page.addInitScript({content:boot+"\nlocalStorage.setItem('ga.ios.hint.newChat','1');"});await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForFunction(()=>window.GAIOS);
  await page.evaluate(css=>{
   window.__gaPresence={css};window.presenceCalls=[];
   window.webkit={messageHandlers:{gaPresence:{postMessage:m=>presenceCalls.push(m)}}};
   renderConvo({id:'presence-layout',title:'布局测试',msgs:[{role:'user',text:'查看手机并等待我接管'}]});
  },fs.readFileSync(root+'/ios/Presence/Web/presence.css','utf8'));
  await page.addScriptTag({content:fs.readFileSync(root+'/ios/Presence/Web/presence.js','utf8')});
  for(const width of [320,390,430])for(const font of [16,53])for(const lang of ['zh','en'])for(const phase of ['acting','paused']){
   const name=`${width}px / ${font}px text / ${lang} / ${phase}`;
   await page.setViewportSize({width,height:932});
   await page.evaluate(({font,lang,phase})=>{
    document.documentElement.style.fontSize=font+'px';
    GAPresence.render({cid:'presence-layout',phase,running:phase==='acting',now:'查看并操作屏幕上的内容，等待页面刷新',status:lang==='en'?'You are in control':'你在操作',
     labels:lang==='en'?{takeOver:'Take over',handBack:'Hand back',handingBack:'Handing back…',end:'End',released:'input released'}:
      {takeOver:'我来操作',handBack:'交还给 GAgent',handingBack:'正在交还…',end:'结束',released:'键鼠已松开'}});
   },{font,lang,phase});
   await page.waitForTimeout(60);
   const metrics=await page.locator('#gaPresence').evaluate(bar=>{
    const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
    return {bar:rect(bar),buttons:[...bar.querySelectorAll('button:not([hidden])')].map(b=>{
     const r=rect(b),target=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
     return {...r,label:b.getAttribute('aria-label'),hit:!!target&&(target===b||b.contains(target)),font:parseFloat(getComputedStyle(b).fontSize)};
    })};
   });
   try{
    for(const b of metrics.buttons){
     assert(b.height>=44&&b.width>=44,`${b.label}: ${b.width} × ${b.height} target`);
     assert(b.x>=metrics.bar.x&&b.right<=metrics.bar.right+1,`${b.label}: outside strip`);
     assert(b.hit,`${b.label}: hit point covered`);
     if(font===53)assert(b.font>40,`${b.label}: large text did not scale`);
    }
    results.push({name,passed:true,metrics});
   }catch(e){results.push({name,passed:false,error:e.message,metrics})}
  }
  await page.screenshot({path:out+'/presence-large-text.png'});
  await page.evaluate(()=>{presenceCalls=[];document.documentElement.style.fontSize='16px'});
  await page.locator('#gaPresence button:not([hidden])').first().click();
  const request=await page.evaluate(()=>presenceCalls[0].request);assert.ok(request);
  assert.deepEqual(await page.evaluate(()=>presenceCalls),[{command:'resume',cid:'presence-layout',request}]);
  assert(await page.locator('#gaPresence button').first().isDisabled(),'hand-back waits for the engine');
  await page.locator('#gaPresence .gpEnd').click();
  assert.deepEqual(await page.evaluate(()=>presenceCalls),[
   {command:'resume',cid:'presence-layout',request},{command:'stop',cid:'presence-layout'}]);
  await page.evaluate(()=>GAPresence.render({cid:'presence-layout',phase:'stopped',running:false}));
  assert(await page.locator('#gaPresence').isHidden(),'ending dismisses the handoff strip');
  await page.evaluate(()=>GAPresence.render({cid:'presence-layout',phase:'paused',running:false,status:'你在操作',
   labels:{handBack:'交还给 GAgent',handingBack:'正在交还…',end:'结束',released:'键鼠已松开'}}));
  assert(await page.locator('#gaPresence button').first().isEnabled(),'a new handoff is not disabled by the ended one');
  await page.evaluate(()=>{curConvo={id:'another-chat'}});await page.waitForTimeout(550);
  assert(await page.locator('#gaPresence').isHidden(),'another conversation cannot own this handoff');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(out+'/results.json',JSON.stringify({results,errors},null,2));
  console.log(`${results.filter(r=>r.passed).length}/${results.length} layout cases passed; hand-back ownership passed. Artifacts: ${out}`);
  if(results.some(r=>!r.passed)){for(const r of results.filter(r=>!r.passed))console.error(r.name+': '+r.error);process.exitCode=1}
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
