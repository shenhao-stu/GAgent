const assert=require('node:assert/strict');
module.exports=async function({page,check,capture,settle}){
  await page.evaluate(()=>{
    window.statsBackup={convos,statRange,customRange};
    const ts=Date.now()-3600e3;
    convos=[{id:'one',ts,msgs:[{role:'user',ts},{role:'assistant',ts,model:'gpt-6.1-sol',ti:10000,to:2000,cr:6000,cw:1000,steps:[{},{}]}]},
      {id:'two',ts,msgs:[{role:'assistant',ts,model:'Claude / very-long-model-name-for-layout',ti:4000,to:2000,steps:[{}]}]},
      {id:'deleted',deleted:true,ts,msgs:[{role:'assistant',ts,model:'excluded',ti:99999,to:99999}]},
      {id:'old',ts:ts-100*864e5,msgs:[{role:'assistant',ts:ts-100*864e5,model:'Older model',ti:1000,to:500}]}];
    statRange='range_30d';openStatsPage();
  });await settle();
  await check('statistics keep real totals, rank models and scale bars from zero',async()=>{
    assert.deepEqual(await page.locator('#statGrid .statNum').allTextContents(),['2','3','14.0k','4.0k','3','6.0k','1.0k','43%']);
    assert.equal(await page.locator('.iosModelUsage').count(),2);
    assert.match(await page.locator('.iosModelName').first().textContent(),/gpt/);
    const widths=await page.locator('.iosModelBar').evaluateAll(es=>es.map(e=>parseFloat(e.style.width)));assert.deepEqual(widths,[100,50]);
    assert.match(await page.locator('.iosModelTrack').first().getAttribute('aria-label'),/10000.*2000/);
    assert.equal(await page.locator('.statRange[aria-pressed=true]').textContent(),'最近 30 天');
    await page.evaluate(()=>{window.savedHeat=$('heatGrid').firstChild;window.savedScroll=$('heatScroll').scrollLeft});
    await page.locator('.statRange').first().click();
    assert.equal(await page.locator('.iosModelUsage').count(),3);
    assert(await page.evaluate(()=>$('heatGrid').firstChild===savedHeat&&$('heatScroll').scrollLeft===savedScroll));
  });
  await check('statistics remain readable in light, dark, large text and narrow layouts',async()=>{
    for(const c of [{w:430,h:932,theme:'light',lang:'zh',size:16},{w:430,h:932,theme:'dark',lang:'zh',size:16},{w:320,h:568,theme:'light',lang:'en',size:24}]){
      await page.setViewportSize({width:c.w,height:c.h});
      await page.evaluate(c=>{setLang(c.lang);document.documentElement.dataset.theme=c.theme;document.documentElement.style.fontSize=c.size+'px';renderStats();document.querySelector('#setv>.setbody').scrollTop=0},c);
      await settle();await capture('stats-'+c.theme+'-'+c.w);
      const geometry=await page.locator('#statsPanel').evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth}));assert(geometry.scroll<=geometry.width);
      assert(await page.locator('.statRange').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44)));
      await page.locator('#modelStats').scrollIntoViewIfNeeded();await capture('stats-models-'+c.theme+'-'+c.w);
      assert.equal(await page.locator('#statsPanel .secLbl>svg').count(),2);
    }
  });
  await check('empty statistics have no invented bars or undefined hit rate',async()=>{
    await page.evaluate(()=>{convos=[];renderStats()});
    assert.equal(await page.locator('.iosModelBar').count(),0);
    assert.equal(await page.locator('#statGrid .statNum').last().textContent(),'—');
    assert.equal(await page.locator('.iosStatsEmpty').count(),1);await capture('stats-empty');
  });
  await page.setViewportSize({width:430,height:932});
  await page.evaluate(()=>{
    setLang('zh');document.documentElement.dataset.theme='light';document.documentElement.style.fontSize='16px';
    ({convos,statRange,customRange}=statsBackup);closeSettings();openSettings();
    window.consentFixture={ok:true,accepted:false,pcAccepted:false,version:'fixture-version',providerSignature:'fixture-signature',
      providerIds:{'模型服务':'one'},receivers:[{providerId:'one',recipients:['你配置的模型服务及其数据处理方'],model:'private-model',endpoint:'https://hidden.example/v1'},
      {providerId:'one',recipients:['你配置的模型服务及其数据处理方'],model:'another-model',endpoint:'https://hidden.example/v1'}]};
    window.savedConsentSend=GA.send;window.consentCalls=[];
    GA.send=cmd=>{
      if(cmd==='/ios.consent.status')return JSON.stringify(consentFixture);
      if(cmd.startsWith('/ios.consent.refresh'))return JSON.stringify({job:'privacy-fixture'});
      if(cmd==='/jobresult privacy-fixture')return JSON.stringify({result:JSON.stringify(consentFixture)});
      if(cmd.startsWith('/ios.consent ')){consentCalls.push(cmd);return JSON.stringify({ok:true,accepted:JSON.parse(cmd.slice('/ios.consent '.length)).accepted})}
      return savedConsentSend(cmd);
    };
  });await settle();
  await check('privacy keeps all disclosures, hides technical routing, and decline never grants',async()=>{
    await page.evaluate(()=>showIOSDataConsent(null,false));await page.waitForTimeout(60);
    assert(await page.locator('#iosConsentAgree').isDisabled());await settle();
    assert.equal(await page.locator('.iosDisclosureSection').count(),6);
    assert.equal(await page.locator('.iosRecipientCard').count(),1);
    const text=await page.locator('.pcBody').textContent();assert(!/private-model|hidden.example/.test(text));
    for(const phrase of ['截图','境外','本机','接收方','导入'])assert(text.includes(phrase));
    await capture('privacy-light');
    for(const c of [{w:430,h:932,theme:'dark',size:16},{w:320,h:568,theme:'light',size:24},{w:844,h:390,theme:'dark',size:16}]){
      await page.setViewportSize({width:c.w,height:c.h});await page.evaluate(c=>{document.documentElement.dataset.theme=c.theme;document.documentElement.style.fontSize=c.size+'px'},c);await settle();
      const r=await page.locator('.privacyCard').evaluate(e=>{const body=e.querySelector('.pcBody').getBoundingClientRect(),foot=e.querySelector('.pcFoot').getBoundingClientRect();return {body:body.toJSON(),foot:foot.toJSON(),width:e.clientWidth,scroll:e.scrollWidth}});
      assert(r.body.height>60);assert(r.body.bottom<=r.foot.top+1);assert(r.foot.bottom<=c.h+1);assert(r.scroll<=r.width);
      assert(await page.locator('.pcFoot button').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44)));
      await capture('privacy-'+c.theme+'-'+c.w);
    }
    await page.locator('#iosConsentDecline').click();assert.equal(await page.evaluate(()=>consentCalls.length),0);
  });
  await check('English privacy decisions fit a narrow large-text screen',async()=>{
    await page.setViewportSize({width:320,height:568});
    await page.evaluate(()=>{setLang('en');document.documentElement.style.fontSize='24px';showIOSDataConsent(null,false)});await settle();
    const dimensions=await page.locator('.privacyCard').evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth,body:e.querySelector('.pcBody').clientHeight}));
    assert(dimensions.scroll<=dimensions.width&&dimensions.body>60);
    assert.equal(await page.locator('#iosConsentAgree').textContent(),'Agree and continue');
    await capture('privacy-english-large');await page.locator('#iosConsentDecline').click();
  });
  await page.setViewportSize({width:430,height:932});
  await page.evaluate(()=>{setLang('zh');document.documentElement.style.fontSize='16px';document.documentElement.dataset.theme='light'});
  await check('privacy agreement uses verified signature; managed Done never rewrites consent',async()=>{
    await page.evaluate(()=>showIOSDataConsent(null,false));await settle();await page.locator('#iosConsentAgree').click();
    assert.match(await page.evaluate(()=>consentCalls.at(-1)),/fixture-signature/);
    await page.evaluate(()=>{consentFixture.accepted=true;consentFixture.pcAccepted=true;showIOSDataConsent(null,true)});await settle();
    assert.equal(await page.locator('#iosConsentAgree').textContent(),'完成');assert.equal(await page.locator('#iosConsentDecline').isVisible(),false);
    const before=await page.evaluate(()=>consentCalls.length);await page.locator('#iosConsentAgree').click();assert.equal(await page.evaluate(()=>consentCalls.length),before);
    await page.evaluate(()=>showIOSDataConsent(null,true));await settle();await page.locator('#iosConsentRevoke').scrollIntoViewIfNeeded();await capture('privacy-choices');
    await page.locator('#iosConsentRevoke').click();assert.equal(await page.evaluate(()=>consentCalls.at(-1)),'/ios.consent {"accepted":false}');
  });
  await page.evaluate(()=>{GA.send=savedConsentSend;closeSettings();openSettings()});await settle();
};
