// Real chat renderer + bridge fixture: native answers are observed, never re-sent by the page.
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {boot}=require('./test_ios_shell_browser.cjs');
const web=path.resolve(__dirname,'../../app/src/main/assets/ga_runtime/webui');
(async()=>{
 const server=http.createServer((req,res)=>{const file=path.join(web,req.url==='/'?'index.html':req.url.split('?')[0]);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file))}catch{res.statusCode=404;res.end()}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
 try{
  const page=await browser.newPage();
  await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());
  const fixtureBoot=process.env.IOS_ASK_MULTI?boot.replace("if(q.fn==='caps')return '{}';","if(q.fn==='caps')return '{\"multi\":true}';"):boot;
  await page.addInitScript({content:fixtureBoot});await page.goto('http://127.0.0.1:'+server.address().port);
  await page.waitForFunction(()=>window.GAIOS);await page.waitForTimeout(400);
  const fixture=async()=>page.evaluate(()=>{
   if(timer)clearInterval(timer);timer=null;running=false;task=null;runs.clear();pendingAsk=null;_askKey=null;
   document.querySelectorAll('.askBox').forEach(e=>e.remove());
   curConvo={id:'native-answer',msgs:[]};runConvo=null;activeCid=curConvo.id;
   renderAskPicker({question:'Pick a color',candidates:['Red','Green','Blue']},41);
  });
  const poll=async(data)=>page.evaluate(data=>render({cid:'native-answer',active_convo:'native-answer',running:false,gen:42,reply_to_gen:41,prompt:'Green',steps:[],...data}),data);
  const answered=()=>page.locator('.askBox.answered').count();
  await fixture();await poll({});
  assert.equal(await answered(),1,'completed native answer closes the old card');
  assert.match(await page.locator('.askDone').textContent(),/Green/);
  assert.equal(await page.locator('.askOpt:disabled').count(),3);
  assert.equal(await page.locator('.askOpt.pick .ol').textContent(),'Green');
  assert.equal(await page.locator('.askCustom').count(),0);
  await poll({});assert.equal(await page.locator('.askDone').count(),1,'repeated poll is idempotent');
  await fixture();await poll({gen:41});assert.equal(await answered(),0,'same generation is not an answer');
  await poll({gen:40});assert.equal(await answered(),0,'old generation cannot answer');
  await poll({cid:'other',active_convo:'other'});assert.equal(await answered(),0,'another conversation cannot answer');
  await poll({prompt:''});assert.equal(await answered(),0,'an empty reset is not an answer');
  await poll({gen:43,running:true,active_convo:undefined,prompt:'A custom answer'});
  assert.equal(await answered(),1,'in-flight native answer also closes the card');
  assert.match(await page.locator('.askDone').textContent(),/A custom answer/);
  await fixture();await poll({gen:44,reply_to_gen:43,prompt:'later answer'});
  assert.equal(await page.locator('.askBox').count(),0,'skipped native questions invalidate old controls without inventing an answer');
  await fixture();await page.evaluate(()=>GA.platform='android');await poll({});
  assert.equal(await answered(),0,'Android behavior stays unchanged');
  await page.evaluate(()=>GA.platform='ios');
  const completedQuestion=async()=>page.evaluate(()=>{
   if(timer)clearInterval(timer);timer=null;
   clearInterval(window._gaIdlePoll);running=false;runs.clear();task=null;_askKey=null;
   chat.innerHTML='';curConvo={id:'native-answer',msgs:[{role:'user',text:'Pick a color'}]};
   convos=[curConvo];runConvo=null;activeCid=curConvo.id;startNew=false;
   userBubble('Pick a color');newTask('Pick a color');task._gen=41;
   setStep({n:1,summary:'Question',text:'Please select a color.'});finish();setRunning(false,curConvo.id);
   renderAskPicker({question:'Pick a color',candidates:['Red','Green','Blue']},41);
  });
  const result={final:'Selected Green.',nsteps:1,steps:[{n:1,summary:'Answer',text:'Selected Green.'}]};
  await completedQuestion();await poll(result);
  const transcript=()=>page.evaluate(()=>({msgs:curConvo.msgs,gen:task._gen,done:task.done,text:chat.textContent}));
  let state=await transcript();
  assert.deepEqual(state.msgs.map(m=>m.role),['user','assistant','user','assistant'],'a completed native turn creates its own two messages');
  assert.equal(state.msgs[1].final,'Please select a color.','the old question remains intact');
  assert.equal(state.msgs[2].text,'Green');assert.equal(state.msgs[3].final,'Selected Green.');
  assert.equal(state.gen,42);assert.equal(state.done,true);assert.match(state.text,/Selected Green/);
  await poll(result);await poll({gen:41,prompt:'Pick a color',steps:[{n:1,text:'Stale reply'}]});
  state=await transcript();assert.equal(state.msgs.length,4);assert.equal(state.msgs[3].final,'Selected Green.');
  await poll({...result,cid:'other',gen:43,prompt:'Wrong conversation'});
  state=await transcript();assert.equal(state.msgs.length,4);assert.equal(state.gen,42);
  await completedQuestion();await poll({...result,active_convo:'another-backend-focus'});
  state=await transcript();assert.equal(state.msgs.length,4);assert.equal(state.msgs[3].final,'Selected Green.');
  await completedQuestion();await poll({...result,running:true});await poll(result);
  state=await transcript();assert.equal(state.msgs.length,4);assert.equal(state.msgs[3].final,'Selected Green.');
  await completedQuestion();await page.evaluate(()=>{task.done=false;setRunning(true,curConvo.id)});await poll(result);
  state=await transcript();assert.equal(state.msgs.length,4);assert.equal(state.msgs[1].final,'Please select a color.');
  await completedQuestion();
  const cursor=await page.evaluate(result=>{
   setStep({n:2,summary:'More',text:'Question context'});setStep({n:3,summary:'Asked',text:'Please choose'});finish();
   const fn=multi?'pollC':'poll',original=GA[fn],calls=[];
   GA[fn]=(...args)=>{const since=Number(args[args.length-1]);calls.push(since);return JSON.stringify({cid:'native-answer',active_convo:'native-answer',running:false,gen:42,reply_to_gen:41,prompt:'Green',...result,steps:result.steps.slice(since)})};
   try{poll()}finally{GA[fn]=original}
   return {calls,msgs:curConvo.msgs};
  },result);
  assert.deepEqual(cursor.calls,[2,0],'a new generation re-reads steps from zero');
  assert.equal(cursor.msgs.length,4);assert.equal(cursor.msgs[3].final,'Selected Green.');
  // Keep the existing page-send failure behavior: no false answered mark on refusal.
  await fixture();await page.evaluate(()=>{startTask=()=>false;answerAsk(document.querySelector('.askBox'),'Green')});
  assert.equal(await answered(),0);assert.equal(await page.locator('.askCustom').count(),1);
  console.log('PASS: native completed/in-flight transcripts, generation cursor reset, preserved old turns, selected option and disabled controls, duplicate/old/foreign/empty polls, Android isolation, rejected page send.');
 }finally{await browser.close();await new Promise(r=>server.close(r))}
})().catch(e=>{console.error(e);process.exitCode=1});
