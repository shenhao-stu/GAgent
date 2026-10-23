/* Optional service adapters. Tokens are accepted on save and never read back into the UI. */
function openIntegrations(){
  const english=lang==='en';
  let config={};
  try{config=JSON.parse(GA.send('/integrations.get')||'{}')}catch(e){toast(String(e));return}
  const panel=document.createElement('div');
  panel.className='modalCard';
  const title=document.createElement('h3');title.textContent=english?'Optional modules':'可选组件';panel.appendChild(title);
  const hint=document.createElement('p');hint.className='hint';
  hint.textContent=english?'PC Link can use build-provided defaults; blank PC Link URL restores them. Other blank URLs disable the module. Blank tokens retain saved values only for unchanged URLs.':'PC Link 可使用安装包的默认服务；清空 PC Link 地址恢复默认，其他组件清空地址停用。令牌留空仅在地址未变时保留旧值。';panel.appendChild(hint);
  const models=document.createElement('button');models.textContent=english?'Model provider / GA Plan':'模型服务商 / GA Plan';
  models.onclick=()=>{overlay.remove();openProviders()};panel.appendChild(models);
  const upload=document.createElement('input');upload.type='file';upload.accept='.json,application/json';
  upload.setAttribute('aria-label',english?'Import connection profile':'导入连接配置');panel.appendChild(upload);
  upload.onchange=async()=>{
    try{
      const file=upload.files[0];if(!file)return;if(file.size>65536)throw Error('Profile exceeds 64 KiB');
      const profile=JSON.parse(await file.text());
      if(profile.schema!==1||!profile.integrations||typeof profile.integrations!=='object')throw Error('Invalid profile schema');
      for(const [name,values] of Object.entries(profile.integrations)){
        if(!inputs[name]||!values||typeof values!=='object')throw Error('Unknown module');
        for(const [field,value] of Object.entries(values)){
          if(!inputs[name][field]||typeof value!=='string')throw Error('Invalid field');
        }
      }
      for(const [name,values] of Object.entries(profile.integrations)){
        for(const [field,input] of Object.entries(inputs[name]))input.value=values[field]||'';
      }
      error.textContent=english?'Review addresses and credentials, then Save to enable.':'请检查地址和凭据，点击保存后才启用。';
    }catch(e){error.textContent=String(e)}finally{upload.value=''}
  };
  const specs={pclink:['url','token'],ganet:['url','token','owner_id'],voice:['url','token','model'],apk:['url','token']};
  const inputs={};
  for(const [name,fields] of Object.entries(specs)){
    const heading=document.createElement('h4');heading.textContent={pclink:'PC Link',ganet:'Mesh / GAnet',voice:'Streaming ASR',apk:'APK build service'}[name];panel.appendChild(heading);
    inputs[name]={};
    for(const field of fields){
      const label=document.createElement('label');label.textContent=field;label.style.display='block';
      const input=document.createElement('input');input.type=field==='token'?'password':'text';input.autocomplete='off';input.spellcheck=false;
      input.style.cssText='width:100%;box-sizing:border-box;padding:9px;margin:4px 0 8px';
      input.value=field==='token'?'':((config[name]||{})[field]||'');
      if(field==='token'&&(config[name]||{}).has_token)input.placeholder=english?'Saved (leave blank to retain)':'已保存（留空保留）';
      label.appendChild(input);panel.appendChild(label);inputs[name][field]=input;
    }
  }
  const error=document.createElement('p');error.style.color='var(--danger,#d33)';panel.appendChild(error);
  const save=document.createElement('button');save.className='btnPrimary';save.textContent=english?'Save':'保存';
  save.onclick=()=>{
    const payload={};for(const [name,fields] of Object.entries(inputs))payload[name]=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.value]));
    try{const result=JSON.parse(GA.send('/integrations.save '+JSON.stringify(payload))||'{}');if(!result.ok){error.textContent=result.error||'Save failed';return}overlay.remove();toast(english?'Saved':'已保存')}
    catch(e){error.textContent=String(e)}
  };
  const close=document.createElement('button');close.textContent=english?'Cancel':'取消';close.onclick=()=>overlay.remove();
  panel.appendChild(save);panel.appendChild(close);
  const overlay=document.createElement('div');overlay.style.cssText='position:fixed;inset:0;z-index:10000;background:#0008;display:grid;place-items:center;padding:24px;overflow:auto';
  panel.style.cssText='background:var(--bg,#fff);color:var(--fg,#111);padding:20px;max-height:85vh;overflow:auto;border-radius:16px;width:min(520px,100%)';
  overlay.appendChild(panel);document.body.appendChild(overlay);
}
