const assert=require('node:assert/strict');
module.exports=async function({page,check,capture,settle}){
  await page.evaluate(()=>{
    window.fileFixture={send:GA.send,preview:GA.previewFile,result:'ok',calls:[]};
    GA.previewFile=path=>{fileFixture.calls.push(path);return fileFixture.result};
    GA.send=cmd=>{
      if(cmd==='/mem.list')return JSON.stringify({files:[{name:'phone_use_ios',rel:'phone_use_ios.md',desc:'iPhone 操作：截图、识别与蓝牙键鼠',group:'sop',size:5200,mtime:1794000000},
        {name:'long_name_for_memory_and_skill_with_no_truncation',rel:'long.md',desc:'内容标题完整显示，较长的名称与说明可以自然换行。',group:'sop',size:1200,mtime:1794000000}]});
      if(cmd.startsWith('/mem.read'))return JSON.stringify({ok:true,kind:'md',text:'# iPhone 操作\n\n先读取当前截图，再根据画面确认操作目标。\n\n## 操作步骤\n\n1. 确认屏幕共享已开启\n2. 读取当前画面\n3. 核对操作结果'});
      if(cmd==='/files.list')return JSON.stringify({files:['项目汇报.pptx','音乐示例.m4a','演示视频.mp4','技术说明.pdf'].map(name=>({name,path:'exports/'+name,size:10240}))});
      if(cmd.startsWith('/files.read')){fileFixture.calls.push(cmd);return JSON.stringify({ok:true,kind:'other'})}
      return fileFixture.send(cmd);
    };
  });
  await check('file and memory names remain readable and wrap at large text sizes',async()=>{
    for(const c of [{w:430,h:932,theme:'dark',size:16},{w:320,h:568,theme:'light',size:24}]){
      await page.setViewportSize({width:c.w,height:c.h});await page.evaluate(c=>{document.documentElement.dataset.theme=c.theme;document.documentElement.style.fontSize=c.size+'px';openMemPage()},c);await settle();
      const rows=await page.locator('#memList .fileRow').evaluateAll(es=>es.map(e=>({font:parseFloat(getComputedStyle(e.querySelector('.fNm')).fontSize),meta:parseFloat(getComputedStyle(e.querySelector('.fMeta')).fontSize),width:e.clientWidth,scroll:e.scrollWidth,height:e.clientHeight})));
      assert(rows.every(r=>r.font>=17&&r.meta>=13&&r.scroll<=r.width&&r.height>=44),JSON.stringify(rows));assert(await page.locator('#memList .fileRow').evaluateAll(es=>es.every(e=>e.querySelector('.memDesc').getBoundingClientRect().bottom<=e.querySelector('.fMeta').getBoundingClientRect().top)));await capture('memory-'+c.w+'-'+c.theme);
      await page.locator('#memList .fileRow').first().click();await settle();
      assert(await page.locator('.fpMd').evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=16));
      assert.equal(await page.locator('#filePrev .fpAct').count(),0);await capture('memory-reader-'+c.w);await page.evaluate(()=>closeFilePreview());
      await page.evaluate(()=>openFilesPage());await settle();await capture('generated-files-'+c.w);
    }
  });
  await check('iOS office and media use native preview; unsupported types keep a fallback',async()=>{
    await page.evaluate(()=>{for(const ext of ['pptx','pdf','m4a','mp4','docx','xlsx'])openFilePreview(encodeURIComponent('demo.'+ext))});
    assert.deepEqual(await page.evaluate(()=>fileFixture.calls),['demo.pptx','demo.pdf','demo.m4a','demo.mp4','demo.docx','demo.xlsx']);
    await page.evaluate(()=>{fileFixture.result='err:not-found';openFilePreview('missing.pdf')});
    assert.equal(await page.locator('#filePrev').isVisible(),false);
    await page.evaluate(()=>{fileFixture.result='err:unsupported';openFilePreview('unknown.pptx')});await settle();
    assert(await page.locator('#filePrev .fpInfo').isVisible());assert(await page.evaluate(()=>fileFixture.calls.includes('/files.read unknown.pptx')));
    await page.evaluate(()=>{closeFilePreview();GA.send=fileFixture.send;GA.previewFile=fileFixture.preview;closeSettings();openSettings();document.documentElement.style.fontSize='16px'});
  });
  await page.setViewportSize({width:430,height:932});await settle();
};
