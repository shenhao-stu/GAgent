/* PC-owned configuration. The phone never substitutes its own providers or credentials. */
(function(){
  if(window.GA?.platform!=='ios')return;
  const copy=(zh,en)=>document.documentElement.lang==='en'?en:zh;
  const effortName=value=>({default:copy('电脑默认','Computer default'),low:copy('轻量','Low'),medium:copy('标准','Medium'),high:copy('深入','High'),xhigh:copy('更深入','Extra high'),max:copy('最高','Maximum'),mixed:copy('按渠道设置','Per provider')})[value]||value;
  let button,label,context,sheet;
  function close(){
    if(!sheet)return;
    const old=sheet;sheet=null;button.setAttribute('aria-expanded','false');old.classList.add('out');old.inert=true;old.setAttribute('aria-hidden','true');
    setTimeout(()=>old.remove(),180);button?.focus({preventScroll:true});
  }
  function update(){
    if(!button)return;
    const name=copy('电脑模型','Computer model');if(label.textContent!==name)label.textContent=name;
    const current=context.current();
    button.disabled=!current.peer||!current.connected;
    button.setAttribute('aria-label',copy('选择电脑渠道、模型与思考强度','Choose computer provider, model and reasoning'));
    button.title=button.disabled?copy('先选择一个已连接的电脑会话','Select a connected computer conversation'):button.getAttribute('aria-label');
    if(sheet&&(sheet.peer!==current.peer||sheet.version!==current.version))close();
  }
  function open(){
    const target=context.current();if(!target.peer||!target.connected)return;
    close();const view=document.createElement('div');sheet=view;button.setAttribute('aria-expanded','true');
    view.className='iosPCModelOverlay';view.peer=target.peer;view.version=target.version;
    view.innerHTML='<div class="iosPCModelMask"></div><section class="iosPCModelSheet on" role="dialog" aria-modal="true" aria-labelledby="pcModelTitle"><header><div><h2 id="pcModelTitle"></h2><p></p></div><button type="button" class="pcModelDone"></button></header><div class="pcModelContent" aria-live="polite"></div></section>';
    view.querySelector('h2').textContent=copy('电脑模型','Computer model');
    view.querySelector('header p').textContent=copy('仅作用于当前电脑会话','Applies to this computer conversation');
    const done=view.querySelector('.pcModelDone');done.textContent=copy('完成','Done');done.onclick=close;
    view.querySelector('.iosPCModelMask').onclick=close;
    view.addEventListener('keydown',e=>{
      if(e.key==='Escape')close();
      if(e.key==='Tab'){
        const nodes=[...view.querySelectorAll('button:not(:disabled),select:not(:disabled)')],a=nodes[0],z=nodes.at(-1);
        if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}
        else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}
      }
    });
    document.body.append(view);done.focus({preventScroll:true});
    if(typeof iosBindSheetDrag==='function')iosBindSheetDrag(view.querySelector('section'),view.querySelector('header'),close,()=>true,view.querySelector('.iosPCModelMask'));
    const content=view.querySelector('.pcModelContent');
    const alive=()=>sheet===view&&context.current().peer===target.peer&&context.current().version===target.version;
    const path='/api/'+encodeURIComponent(target.peer);
    function status(text){content.replaceChildren();const p=document.createElement('p');p.className='pcModelNote';p.textContent=text;content.append(p)}
    function request(method,suffix,body,done){context.request(method,path+suffix,body,result=>{if(alive())done(result)})}
    function fail(result){status(result?.error||copy('无法读取电脑模型，请稍后重试','Could not read computer models'));const retry=document.createElement('button');retry.className='pcModelSave';retry.textContent=copy('重试','Retry');retry.onclick=load;content.append(retry)}
    function render(state,legacy=false){
      if(!Array.isArray(state.profiles)||!state.profiles.length)return status(copy('请先在电脑上配置模型','Configure models on your computer first'));
      content.replaceChildren();let selected=state.selected;
      const list=document.createElement('div');list.className='pcModelList';list.setAttribute('role','group');list.setAttribute('aria-label',copy('渠道与模型','Providers and models'));content.append(list);
      const reasoning=document.createElement('label');reasoning.className='pcReasoning';
      const label=document.createElement('span');label.textContent=copy('思考强度','Reasoning effort');
      const select=document.createElement('select');select.id='pcReasoning';reasoning.append(label,select);content.append(reasoning);
      const note=document.createElement('p');note.className='pcModelNote';content.append(note);
      const error=document.createElement('p');error.className='pcModelError';error.setAttribute('role','alert');content.append(error);
      const save=document.createElement('button');save.className='pcModelSave';save.textContent=copy('应用到此会话','Apply to this conversation');content.append(save);
      function choose(profile){
        selected=profile.id;list.querySelectorAll('button').forEach(row=>row.setAttribute('aria-pressed',String(row.dataset.id===selected)));
        const choices=profile.reasoning?.choices||[];select.replaceChildren();
        ['default',...choices].forEach(value=>{const o=document.createElement('option');o.value=value;o.textContent=effortName(value);select.append(o)});
        select.value=choices.includes(profile.reasoning?.value)?profile.reasoning.value:'default';
        select.disabled=legacy||!choices.length||state.busy||target.running;
        reasoning.hidden=legacy;
        note.textContent=(state.busy||target.running)?copy('任务运行中，结束后可调整。','Finish the current task before changing models.'):legacy?copy('此电脑支持切换已配置渠道；思考强度沿用电脑设置。','Choose a configured provider. Reasoning follows the computer settings.'):choices.length?copy('保留对话内容，下一条消息使用新设置。','Keeps the conversation; the next message uses these settings.'):copy('此渠道未开放独立思考强度，沿用电脑设置。','This provider uses its computer-configured reasoning settings.');
        save.disabled=state.busy||target.running;
      }
      for(const profile of state.profiles){
        const row=document.createElement('button');row.type='button';row.className='pcModelOption';row.dataset.id=profile.id;
        const text=document.createElement('span'),name=document.createElement('b'),model=document.createElement('small'),mark=document.createElement('span');
        name.textContent=profile.name;model.textContent=(profile.models||[]).join(' · ');mark.textContent='✓';mark.className='pcModelCheck';mark.setAttribute('aria-hidden','true');
        text.append(name,model);row.append(text,mark);row.onclick=()=>choose(profile);row.disabled=state.busy||target.running;list.append(row);
      }
      choose(state.profiles.find(p=>p.id===selected)||state.profiles[0]);
      save.onclick=()=>{
        if(save.disabled)return;save.disabled=true;error.textContent='';
        list.querySelectorAll('button').forEach(row=>row.disabled=true);select.disabled=true;
        const profile=state.profiles.find(p=>p.id===selected);
        request('POST',legacy?'/llm':'/model_settings',legacy?{no:profile.index}:{revision:state.revision,profile:selected,reasoning:select.value},result=>{
          if(result?.error){if(result.code==='conflict'||result.code==='busy'){load();toast(result.error);return}render(state,legacy);view.querySelector('.pcModelError').textContent=result.error;return}
          close();context.changed();toast(copy('已更新电脑会话模型','Computer conversation model updated'));
        });
      };
    }
    function load(){
      status(copy('正在读取电脑配置…','Loading computer configuration…'));
      request('GET','/model_settings',null,result=>{
        if(result?.profiles)return render(result);
        if(![404,405,501].includes(result?.status)&&!['nosupport','gone'].includes(result?.code))return fail(result);
        request('GET','/llms',null,old=>{
          if(!Array.isArray(old?.items))return fail(old);
          render({selected:String(old.cur),profiles:old.items.map((name,index)=>({id:String(index),index,name,models:[]}))},true);
        });
      });
    }
    load();
  }
  window.IOSPCModels={bind:(b,options)=>{
    button=b;context=options;
    button.innerHTML='<span class="pcModelLabel"></span><svg class="pcModelChevron" aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m4 6 4 4 4-4"/></svg>';
    label=button.querySelector('.pcModelLabel');
    button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');
    button.onclick=open;update();
  },update,close};
})();
