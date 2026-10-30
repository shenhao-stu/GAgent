/* ════════════ 浏览器预览垫片(真机上 Kotlin 注入原生 GA, 此分支不触发) ════════════ */
if(typeof window.GA==='undefined'){
  const demoMd='## 任务完成\n已分析仓库并修复问题。\n\n```python\ndef fib(n):\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a\n```\n\n- 第一步：定位\n- 第二步：修复\n\n行内 `code` 与 **加粗** 正常。';
  const hist=[{prompt:'分析这个仓库并修复 fib 的 bug',final:'已修复',steps:[
    {n:1,summary:'读取项目结构并定位 fib 实现',text:'<summary>读取项目结构</summary>\n扫描目录…找到 `utils.py:fib`。'},
    {n:2,summary:'修复迭代边界并验证',text:demoMd}]}];
  let s={running:false,status:'就绪',gen:1,steps:[],final:'',prompt:'',tok_in:0,tok_out:0},tick=0;
  window.GA={ ready:()=>'ok', isDark:()=>matchMedia('(prefers-color-scheme:dark)').matches,
    poll:(q)=>{q=+q||0;if(s.running){tick++;
        if(tick===1){s.steps=[{n:1,summary:'规划执行步骤',text:'**LLM Running (Turn 1) ...**\n\n<summary>规划执行步骤</summary>\n拆解任务…'}];s.tok_in=1840;s.tok_out=120}
        if(tick===2){s.steps.push({n:2,summary:'执行中：运行代码',text:'```bash\n$ pytest -q\n```\n运行测试…'});s.tok_in=4210;s.tok_out=480}
        if(tick>=4){s.running=false;s.status='完成 · 2步';s.tok_in=5234;s.tok_out=712;
          s.steps[1]=s.ask?{n:2,summary:'请用户选择',text:'🛠️ Tool: `ask_user`  📥 args:\n````text\n{\n  "candidates": ["A. 继续当前对话","B. 测试工具完成","C. 让我再问一个问题"],\n  "question": "请选择一个选项："\n}\n````\nWaiting for your answer ...'}:{n:2,summary:'执行完成',text:demoMd}}}
      const d={running:s.running,status:s.status,gen:s.gen,final:s.final,prompt:s.prompt,nsteps:s.steps.length,steps:q?s.steps.slice(q):s.steps.slice(),tok_in:s.tok_in,tok_out:s.tok_out};
      d.ask=(!s.running&&s.ask)?{question:'请选择一个选项：',candidates:['A. 继续当前对话','B. 测试工具完成','C. 让我再问一个问题']}:null;
      if(q===0)d.hist=hist;return JSON.stringify(d);},
    send:(t)=>{t=t.trim();if(t.startsWith('/key'))return 'mykey.json 已保存(demo)';
      if(t==='/config')return JSON.stringify({ok:true,proxy:'',providers:[
        {id:'mk_0',type:'oai',name:'demo-oai',apikey:'sk-demo',apibase:'https://api.openai.com',model:'gpt-5.4',models:['gpt-5.4'],enabled:true,reasoning:'high'},
        {id:'mk_1',type:'claude',name:'demo-claude',apikey:'sk-demo',apibase:'https://api.openai.com',model:'claude-opus-4-8',models:['claude-opus-4-8'],enabled:true,fake_cc:true}]});
      if(t.startsWith('/proxy'))return '代理已设置: '+t.slice(6).trim();
      if(t.startsWith('/lang'))return 'lang ok';
      if(t.startsWith('/clear')){hist.length=0;s.gen++;return 'cleared'}
      if(t.startsWith('/models')){window._djs=window._djs||{};window._djn=(window._djn||0)+1;const id='d'+window._djn;
        window._djs[id]={n:0,r:JSON.stringify({ok:true,models:['gpt-5.5','gpt-5.4','gpt-5.3-codex','o4-mini','claude-opus-4-8','claude-sonnet-4-6','gemini-3-pro','deepseek-v4','grok-4','qwen-max']})};return JSON.stringify({job:id})}
      if(t.startsWith('/share.summary ')){window._djs=window._djs||{};window._djn=(window._djn||0)+1;const id='s'+window._djn;   // demo: 模拟模型蒸馏返回
        window._djs[id]={n:0,r:JSON.stringify({ok:true,title:'用 GA 做了个简洁日历 APK',points:['命中 APK 工厂 SOP 流程','降级 SDK34 绕过编译失败','装机验证已成功打开'],outcome:'雅致日历 APK 已装机并打开'})};return JSON.stringify({job:id})}
      if(t.startsWith('/jobresult')){const id=t.slice(10).trim();const dj=(window._djs||{})[id];if(!dj)return JSON.stringify({pending:false,result:'{}'});
        if(dj.n++<2)return JSON.stringify({pending:true});const r=dj.r;delete window._djs[id];return JSON.stringify({pending:false,result:r})}
      if(/^\/(session\.|llm )/.test(t))return '✅ '+t.slice(1)+' (demo)';
      if(t.startsWith('/kv.set ')){const r=t.slice(8),sp=r.indexOf(' ');window._kv=window._kv||{};window._kv[r.slice(0,sp)]=r.slice(sp+1);return 'ok'}
      if(t.startsWith('/kv.get '))return (window._kv||{})[t.slice(8).trim()]||'';
      if(t.startsWith('/kv.del '))return 'ok';
      if(t==='/detectproxy')return JSON.stringify({proxy:'http://127.0.0.1:10809'});
      if(t==='/storageinfo')return JSON.stringify({path:'/data/data/com.ljq.ga/files/ga',used:1916825,app_used:52428800,free:8589934592,temp:1069056,clearable:1069056,cats:[{key:'chats',size:127590,count:6},{key:'assistant',size:453939,count:3},{key:'images',size:0,count:0},{key:'files',size:0,count:0},{key:'cache',size:1069056,count:7},{key:'updcache',size:8388608,count:1},{key:'evobak',size:262144,count:2},{key:'system',size:0,count:0},{key:'logs',size:4096,count:2}]});
      if(t==='/cleartemp')return JSON.stringify({removed:3});
      if(t==='/clearupdcache')return JSON.stringify({removed:1});
      if(t==='/evo.status')return JSON.stringify({baseline:true,backups:[{name:'pre-2.2-demo.zip',count:3,oldVer:'2.2',newVer:'2.3',ts:1}],latest:{name:'pre-2.2-demo.zip',count:3,oldVer:'2.2',newVer:'2.3',ts:1}});
      if(t.startsWith('/evo.fuseprompt'))return JSON.stringify({ok:true,prompt:'[demo] evolve-merge hidden prompt — three-way merge base/ours/live …',files:3,oldVer:'2.2'});
      if(t==='/evo.clearbackups')return JSON.stringify({ok:true,removed:2});
      if(t.startsWith('/rollback'))return 'ok';
      s={running:true,status:'思考中',gen:s.gen+1,steps:[],final:'',prompt:t,ask:/ask|单选|多选|choose|option|选项/i.test(t)};tick=0;return '';},
    abort:()=>{s.running=false;s.status='已中止';}, float:()=>alert('悬浮窗(demo)'), setFloatAlwaysOn:(b)=>{alert('悬浮窗常开(demo): '+b);return b},
    openBrowser:()=>alert('内置浏览器(demo): 空白页'),
    appVersion:()=>JSON.stringify({name:'1.1',code:42,channel:window._otaChDemo||'official',buildChannel:'official'}),
    openUrl:(u)=>{try{window.open(u,'_blank')}catch(e){}},
    otaChannel:()=>JSON.stringify({channel:window._otaChDemo||'official',build:'official',url:(window._otaChDemo==='beta')?'https://example.invalid/beta/latest.json':'https://example.invalid/latest.json'}),
    otaSetChannel:(ch)=>{window._otaChDemo=(ch==='beta')?'beta':'official';return JSON.stringify({ok:true,channel:window._otaChDemo,build:'official'})},
    otaManifest:()=>JSON.stringify({versionCode:43,versionName:'1.2',channel:window._otaChDemo||'official',url:'https://example.invalid/download/GAgent-1.2-43.apk',size:138412032,sha256:'0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',mandatory:false,publishedAt:'2026-06-23',notes:'## 1.2 更新\n- 演示更新日志\n- 修复若干问题',notes_en:'## 1.2\n- demo changelog',
      heroChips:{v:1,minVc:0,zh:[{icon:'boba',label:'点一杯奶茶(OTA)',prompt:'打开外卖软件，帮我点一杯常喝的奶茶'},{icon:'mail',label:'整理重要邮件',prompt:'查看我的邮箱，整理今天重要的邮件摘要'},{icon:'search',label:'小红书热点',prompt:'在小红书搜索今日热门话题并总结'}],en:[{icon:'boba',label:'Bubble tea (OTA)',prompt:'Order my usual bubble tea'},{icon:'mail',label:'Digest inbox',prompt:'Summarize today’s important emails'},{icon:'search',label:'RED trending',prompt:'Search trending topics on Xiaohongshu'}]}}),
    otaDownload:()=>{window._otaDemo={p:0,s:'downloading'};return '{"ok":true}'},
    otaProgress:()=>{const d=window._otaDemo||{p:0,s:'idle'};if(d.s==='downloading'){d.p+=12;if(d.p>=100){d.p=100;d.s='ready'}}return JSON.stringify({state:d.s,pct:Math.min(100,d.p),ready:d.s==='ready'})},
    otaInstall:()=>{alert('安装(demo)');return '{"ok":true}'},
    saveUpload:(n,d)=>'/data/demo/uploads/'+n,
    a11yEnabled:()=>(window._a11yDemo===undefined?false:window._a11yDemo),  // 预览: 默认未开启, 便于验证横幅/红点; 控制台设 window._a11yDemo=true 模拟已开
    openA11ySettings:()=>{alert('打开系统无障碍设置(demo)');window._a11yDemo=true;setTimeout(()=>{try{gaOnA11y(true)}catch(e){}},400)},
    adbSelfStatus:()=>JSON.stringify({wifi:!!window._adbDemo,paired:!!window._adbDemo,connected:!!window._adbDemo}),  // 预览: 默认未连接; 控制台设 window._adbDemo=true 模拟已连接
    openAdbDevSettings:()=>{alert('打开系统开发者选项(demo)');window._adbDemo=true;setTimeout(()=>{try{gaOnAdb()}catch(e){}},400);return true},  // 返回 true=已打开(真机 Kotlin 同签名)
    // 无障碍持久化(v2.29) demo: _apPermDemo=已授 WRITE_SECURE_SETTINGS, _apEnDemo=自动恢复开关; 一键授权走伪 job(立即成功)
    a11yPersistStatus:()=>JSON.stringify({a11yOn:!!window._a11yDemo,hasWriteSecure:!!window._apPermDemo,persistEnabled:!!window._apEnDemo,selfAdbOn:!!window._adbDemo,grantCmd:'adb shell pm grant com.ljq.ga android.permission.WRITE_SECURE_SETTINGS'}),
    setA11yPersist:(b)=>{window._apEnDemo=!!b},
    a11yReEnableNow:()=>{if(window._apPermDemo)window._a11yDemo=true;return !!window._apPermDemo},
    a11yGrantViaSelfAdb:()=>{window._apJobN=(window._apJobN||0)+1;return 'g'+window._apJobN},
    a11yGrantResult:(id)=>{window._apPermDemo=true;window._apEnDemo=true;window._a11yDemo=true;return 'ok'},
    openAppSysSettings:(w)=>{alert('打开系统设置页(demo): '+w);return true},
    // Shizuku 第二条 shell 通道 demo: _szDemo=已授权; 控制台设 window._szDemo=true 模拟就绪
    shizukuStatus:()=>JSON.stringify({installed:true,ready:!!window._szDemo}),
    shizukuRequest:()=>{alert('请求 Shizuku 授权(demo)');window._szDemo=true;setTimeout(()=>{try{gaOnShizuku()}catch(e){}},400)},
    openShizukuManager:()=>{alert('打开 Shizuku 管理器(demo)');return true},
    saveImageToGallery:(d)=>{try{window.open(d,'_blank')}catch(e){}return 'ok'},   // demo: 浏览器新开图片页代替存相册
    shareImage:(d)=>{alert('转发(demo): 已生成分享图');return 'ok'},
    // 诊断/上传 demo: 立即完成的伪 job(diagResult 首次返回 pending, 次次返回结果), 便于预览三条通道 UI
    logError:(tag,msg)=>{try{console.log('[logError]',tag,msg)}catch(e){}},
    logsUpload:()=>{window._djs=window._djs||{};window._djn=(window._djn||0)+1;const id='u'+window._djn;window._djs[id]={n:0,r:JSON.stringify({ok:true,files:2})};return id},
    promptContribute:(text,cid)=>{try{console.log('[promptContribute]',cid,String(text).slice(0,40))}catch(e){}},   // 提问采集 demo: 仅打印, 不落任何东西
    feedbackSubmit:(j)=>{window._djs=window._djs||{};window._djn=(window._djn||0)+1;const id='f'+window._djn;window._djs[id]={n:0,r:JSON.stringify({ok:true})};return id},
    diagResult:(id)=>{const dj=(window._djs||{})[id];if(!dj)return 'err:unknown-id';if(dj.n++<1)return 'pending';const r=dj.r;delete window._djs[id];return r},
    // P3a demo multi-session caps / multi-route bridges (delegate to legacy for local preview)
    caps: ()=> ({multi:true, version:1, maxconc:3}),
    sendC: (cid,t)=> GA.send(t),
    pollC: (cid,since)=> GA.poll(since),
    pollAll: ()=> [],
    abortC: (cid)=> GA.abort() };
}

