// Provider editor and model list on iOS: whose logo a model gets, where the 1M switch appears, and how
// a connection test or a model fetch reports. Real WebUI and bridge; the model service is the fixture.
const assert=require('node:assert/strict');
const timedOut="ConnectTimeout: HTTPSConnectionPool(host='example.test', port=443): Max retries exceeded with url: /v1/models (Caused by ConnectTimeoutError(<urllib3.connection.HTTPSConnection object at 0x10f3a3a10>, 'Connection to example.test timed out. (connect timeout=10)'))";
const reason='ConnectTimeout: Connection to example.test timed out. (connect timeout=10)';
module.exports=async function({page,check,capture,settle}){
  const editor=async id=>{await page.evaluate(id=>{closeSettings();openSettings();openProviders();editProvider(id)},id);await settle()};
  const button=()=>page.evaluate(()=>{const b=$('setvTest'),r=b.getBoundingClientRect(),s=getComputedStyle(b);
    return {state:b.dataset.state,text:b.innerText.trim(),busy:b.getAttribute('aria-busy'),spin:b.classList.contains('spin'),dim:b.classList.contains('dim'),
      animation:s.animationName,transform:s.transform,width:r.width,height:r.height}});
  // One test from tap to answer: the tap asks before the key leaves the phone, and the fixture answers at once.
  const test=async answer=>{await page.evaluate(m=>{demoState.models=m},answer);await page.locator('#setvTest').click();await page.locator('#modalCard .ok').click();await page.waitForTimeout(80)};
  const toast=()=>page.locator('#toast').evaluate(e=>{const r=e.getBoundingClientRect();return {text:e.textContent,on:e.classList.contains('on'),left:r.left,right:r.right,spill:e.scrollWidth-e.clientWidth}});
  const rows=()=>page.evaluate(()=>{
    const plain=html=>html.replace(/_g[0-9a-z]+/g,'');   // each rendered tile gets its own gradient ids
    const brandOf=glyph=>Object.keys(BRAND).find(key=>{const probe=document.createElement('div');probe.innerHTML=brandTile(key);return plain(probe.firstChild.outerHTML)===plain(glyph.outerHTML)});
    return [...document.querySelectorAll('#mlBody .mrow')].map(row=>{const chip=row.querySelector('.m1mBtn');
      return {model:row.querySelector('.mname').textContent,brand:brandOf(row.querySelector('.glyph')),m1m:chip?chip.getAttribute('aria-pressed'):null}});
  });
  const by=(list,field)=>Object.fromEntries(list.map(row=>[row.model,row[field]]));
  await page.evaluate(()=>{
    window.providerBackup={providers,active};
    const provider=(id,name,model,models)=>({id,name,label:name,type:'claude',enabled:true,apikey:'fixture-only',apibase:'https://example.test',model,models});
    providers=[provider('pstep','Stepfun','step-3.7-flash',['step-3.7-flash','stepaudio-2.5-asr','claude-opus-5','claude-sonnet-5[1m]','newly-listed-model']),
               provider('prelay','claude-native','newly-listed-model',['newly-listed-model','gpt-6.1-sol'])];   // the name the editor gives an unnamed Anthropic-type provider
    active={pid:'pstep',model:'step-3.7-flash'};
  });

  await check('a logo names the maker of a model, never the protocol of its endpoint',async()=>{
    await editor('pstep');await page.evaluate(()=>openModelListPage());await settle();
    const stepfun=await rows();
    assert.deepEqual(by(stepfun,'brand'),{'claude-opus-5':'claude','claude-sonnet-5':'claude','step-3.7-flash':'step','stepaudio-2.5-asr':'step','newly-listed-model':'step'});
    await capture('provider-models');
    await page.evaluate(()=>closeModelListPage());await editor('prelay');await page.evaluate(()=>openModelListPage());await settle();
    assert.deepEqual(by(await rows(),'brand'),{'newly-listed-model':'unknown','gpt-6.1-sol':'openai'});
    await capture('provider-models-unnamed');await page.evaluate(()=>closeModelListPage());await settle();
  });
  await check('the 1M switch appears only on Claude models, as a small capsule with a full touch area',async()=>{
    await editor('pstep');await page.evaluate(()=>openModelListPage());await settle();
    assert.deepEqual(by(await rows(),'m1m'),{'claude-opus-5':'false','claude-sonnet-5':'true','step-3.7-flash':null,'stepaudio-2.5-asr':null,'newly-listed-model':null});
    const chip=await page.locator('#mlBody .m1mBtn').first().evaluate(e=>{const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,at=(x,y)=>document.elementFromPoint(x,y)===e;
      return {height:r.height,above:at(x,r.top-8),below:at(x,r.bottom+8),before:at(r.left-4,y),after:at(r.right+4,y)}});
    assert(chip.height<=28&&chip.above&&chip.below&&chip.before&&chip.after,JSON.stringify(chip));
    await page.evaluate(()=>closeModelListPage());await settle();
  });
  await check('editor actions read delete, test, save at one height with their content on the centre line',async()=>{
    await editor('pstep');
    const bar=await page.evaluate(()=>[...document.querySelectorAll('#provSaveBar>button')].filter(b=>b.getClientRects().length).map(b=>{
      const r=b.getBoundingClientRect(),offCentre=e=>{const q=e.getBoundingClientRect();return (q.top+q.bottom-r.top-r.bottom)/2};
      return {id:b.id,name:(b.getAttribute('aria-label')||b.innerText).trim(),left:r.left,height:r.height,offCentre:[...b.querySelectorAll('span,svg')].map(offCentre)}}).sort((a,b)=>a.left-b.left));
    assert.deepEqual(bar.map(b=>[b.id,b.name]),[['provDelBtn','删除'],['setvTest','测试连接'],['saveBtn','保存']]);
    assert(bar.every(b=>b.height>=44&&b.height===bar[0].height),JSON.stringify(bar));
    assert(bar.every(b=>b.offCentre.every(d=>Math.abs(d)<=1)),JSON.stringify(bar));
    await capture('provider-actions');
    await editor(null);   // a provider that does not exist yet has nothing to delete
    assert.deepEqual((await page.locator('#provSaveBar>button:visible').evaluateAll(es=>es.map(e=>e.id))).sort(),['saveBtn','setvTest']);
  });
  await check('the connection test reports on its own button, which keeps its place and shape',async()=>{
    await editor(null);
    assert.equal((await button()).dim,true);await page.locator('#setvTest').click();   // nothing to test yet: say what is missing, ask nothing
    assert.equal(await page.locator('#modalMask').evaluate(e=>e.classList.contains('on')),false);
    assert.equal((await toast()).text,'请先填写 API Key 与 Base URL');
    await editor('pstep');
    const rest=await button();assert.deepEqual([rest.state,rest.text,rest.dim],['idle','测试连接',false]);
    await page.locator('#setvTest').click();
    const busy=await button();assert.deepEqual([busy.state,busy.text,busy.busy],['testing','测试中…','true']);
    // The shared code marks a running test with `.spin`; the button must not turn or shrink because of it.
    assert.deepEqual([busy.spin,busy.animation,busy.transform,busy.width,busy.height],[true,'none','none',rest.width,rest.height]);
    // Declining to send the key is not a failed test.
    await page.locator('#modalCard .cancel').click();
    const declined=await button();assert.deepEqual([declined.state,declined.spin],['idle',false]);
    assert.doesNotMatch((await toast()).text,/失败|取消/);
    await test({ok:true,models:['a','b']});
    const passed=await button();assert.deepEqual([passed.state,passed.text,passed.busy,passed.spin,passed.width],['ok','连接正常','false',false,rest.width]);
    assert.doesNotMatch((await toast()).text,/连接/);   // the button has said it
    await capture('provider-test-ok');
    await page.waitForFunction(()=>$('setvTest').dataset.state==='idle',{},{timeout:4000});
    await test({ok:false,error:timedOut});
    const failed=await button();assert.deepEqual([failed.state,failed.text,failed.width],['failed','连接失败',rest.width]);
    const why=await toast();assert.deepEqual([why.text,why.on],[reason,true]);
    assert(why.left>=16&&why.right<=await page.evaluate(()=>innerWidth)-16&&why.spill<=0,JSON.stringify(why));
    await capture('provider-test-failed');
  });
  await check('a test result that arrives after another provider is opened is not shown',async()=>{
    await editor('pstep');await page.evaluate(()=>{demoState.modelsPending=true;$('toast').textContent=''});
    await page.locator('#setvTest').click();await page.locator('#modalCard .ok').click();
    assert.equal((await button()).state,'testing');
    await editor('prelay');
    const moved=await button();assert.deepEqual([moved.state,moved.spin],['idle',false]);
    await page.evaluate(()=>{demoState.models={ok:false,error:'HTTP 401: denied'};demoState.modelsPending=false});await page.waitForTimeout(900);
    assert.equal((await button()).state,'idle');assert.equal((await toast()).text,'');
  });
  await check('a failed model fetch gives its reason in a toast that fits; declining says nothing',async()=>{
    await editor('pstep');await page.evaluate(()=>{$('toast').textContent='';openModelListPage()});await settle();
    await page.locator('#mlFetch').click();await page.locator('#modalCard .cancel').click();await page.waitForTimeout(80);
    assert.equal((await toast()).text,'');
    await page.evaluate(m=>{demoState.models=m},{ok:false,error:timedOut});
    await page.locator('#mlFetch').click();await page.locator('#modalCard .ok').click();await page.waitForTimeout(350);
    const failed=await toast();assert.deepEqual([failed.text,failed.on],['获取失败：'+reason,true]);
    assert(failed.left>=16&&failed.right<=await page.evaluate(()=>innerWidth)-16&&failed.spill<=0,JSON.stringify(failed));
    assert.equal(await page.locator('#mlBody .mrow').count(),5);   // the list it already had is still there
    await page.evaluate(()=>closeModelListPage());await settle();
  });
  await page.evaluate(()=>{providers=providerBackup.providers;active=providerBackup.active;demoState.models=undefined;closeSettings();openSettings()});await settle();
};
