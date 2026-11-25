const assert=require('node:assert/strict');
module.exports=async function({page,check,capture,settle}){
 await check('quota errors offer a model choice without resubmitting or hiding the original error',async()=>{
  await page.evaluate(()=>{
   closeSettings();GAIOS.navigate('assistant');
   window.issueTest={raw:'**LLM Running (Turn 1) ...**\n\n!!!Error: HTTP 429: {"error":{"code":"1310","message":"Weekly/Monthly Limit Exhausted <img src=x onerror=alert(1)>"}}',choose:openModelSheet,choices:0};
   openModelSheet=()=>issueTest.choices++;
   const card=document.createElement('div');card.id='issueTestCard';card.className='step open';card.innerHTML='<div class="ss"></div><div class="sb"></div>';
   card._final=true;card._text=issueTest.raw;document.getElementById('chat').append(card);renderBody(card);card.scrollIntoView();
  });await settle();
  assert.equal(await page.locator('.iosModelIssue h4').textContent(),'模型额度已用完');
  assert.equal(await page.locator('.iosModelIssue details').getAttribute('open'),null);
  assert.equal(await page.locator('.iosModelIssue img').count(),0);
  assert.equal(await page.locator('.iosModelIssue button').evaluate(e=>e.getBoundingClientRect().height>=44),true);
  await capture('model-quota-error');
  await page.locator('.iosModelIssue button').click();assert.equal(await page.evaluate(()=>issueTest.choices),1);
  assert.equal(await page.evaluate(()=>$('issueTestCard')._text===issueTest.raw),true);
  await page.locator('.iosModelIssue summary').click();assert.match(await page.locator('.iosModelIssue pre').textContent(),/1310/);
  await page.setViewportSize({width:320,height:568});await page.evaluate(()=>document.documentElement.style.fontSize='24px');await settle();
  assert(await page.locator('.iosModelIssue').evaluate(e=>e.scrollWidth<=e.clientWidth));await capture('model-quota-details-narrow');
  await page.evaluate(()=>{openModelSheet=issueTest.choose;$('issueTestCard').remove();document.documentElement.style.fontSize='16px';openSettings()});
  await page.setViewportSize({width:430,height:932});await settle();
 });
};
