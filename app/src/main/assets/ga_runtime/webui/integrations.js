/* Optional service adapters, shown as a Settings subpage so they share the settings theme tokens.
   Tokens are accepted on save and never read back into the UI. */
(function(){
const MODULES={   // field order = service_config.SERVICES; scheme only drives the placeholder, validation stays server-side
  pclink:{fields:['url','token'],scheme:'wss',zh:['电脑互联 PC Link','连接你电脑上的 GA 中继服务'],en:['PC Link','Relay to GA running on your computer']},
  ganet:{fields:['url','token','owner_id'],scheme:'https',zh:['设备组网 Mesh / GAnet','自建 Headscale 等组网与配对服务'],en:['Mesh / GAnet','Your self-hosted mesh and pairing service']},
  voice:{fields:['url','token','model'],scheme:'wss',zh:['流式语音识别','语音输入使用的流式 ASR 服务（如 Step Voice）'],en:['Streaming ASR','Streaming speech recognition for voice input (e.g. Step Voice)']},
  apk:{fields:['url','token'],scheme:'https',zh:['APK 构建服务','APK 工厂使用的云端构建服务'],en:['APK build service','Cloud build service used by the APK factory']},
};
const FIELD={url:['服务地址','Endpoint URL'],token:['访问令牌','Access token'],owner_id:['账户 ID（数字）','Owner ID (numeric)'],model:['模型','Model']};
/* GenericAgent's public PC Link relay. Its access value is the default already published in the open-source
   GenericAgent desktop client (frontends/p2p_ws_client.py), where it filters scans and is not a secret.
   Filled into the form only after the user confirms; nothing is saved until Save. */
const PUBLIC_RELAY={url:'wss://p2p.gaagent.ai/ws',token:'ljq-p2p-ws-default-access-key-v1-7f3c9a2e'};
const PUBLIC_RELAY_NOTE=['公共中继由 GenericAgent 项目运营，访问值已在开源桌面端公开，只用于过滤扫描，不是密码。配对安全依赖电脑上出示的二维码/9 位短码和房间 ID：只在自己电脑上出示配对码、不要外传截图。中继运营方理论上可看到连接元数据，敏感用途请自建中继。电脑端 GA 也需使用同一中继。',
  'The public relay is run by the GenericAgent project. Its access value is already published in the open-source desktop client; it filters scans and is not a password. Pairing relies on the QR or 9-digit code shown on your computer and the room ID: show the code only on your own computer and do not share screenshots. The relay operator could in principle see connection metadata; self-host for sensitive use. Your computer GA must use the same relay.'];
const CHEV='<svg class="chev" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e};

/* Pure: validate an imported profile against the known module/field shape; returns values per module. */
function parseProfile(profile,inputs){
  if(profile.schema!==1||!profile.integrations||typeof profile.integrations!=='object')throw Error('Invalid profile schema');
  for(const [name,values] of Object.entries(profile.integrations)){
    if(!inputs[name]||!values||typeof values!=='object')throw Error('Unknown module');
    for(const [field,value] of Object.entries(values))if(!inputs[name][field]||typeof value!=='string')throw Error('Invalid field');
  }
  return profile.integrations;
}

function openIntegrations(focus){   // focus=module name: scroll its card into view (e.g. PC Link asks for its relay)
  const en=lang==='en',L=pair=>pair[en?1:0];
  let config={};
  try{config=JSON.parse(GA.send('/integrations.get')||'{}')}catch(e){toast(String(e));return}
  if(!setStack.length)openSettings();
  if(!SET_PANELS.includes('integrationsPanel'))SET_PANELS.push('integrationsPanel');
  let panel=document.getElementById('integrationsPanel');
  if(!panel){panel=el('div');panel.id='integrationsPanel';panel.style.display='none';$('homePanel').parentElement.appendChild(panel)}
  panel.replaceChildren();   // rebuilt on every open: fresh saved state + current language, no stale typed secrets
  panel.appendChild(el('p','hint intLead',en?'A blank URL disables its module. A blank token keeps the saved value only while the URL is unchanged.':'地址留空即停用该组件；令牌留空仅在地址未变时保留旧值。'));

  const section=(title,chip)=>{const s=el('div','secLbl');s.appendChild(el('span',null,title));if(chip)s.appendChild(chip);panel.appendChild(s);const c=el('div','card');panel.appendChild(c);return c};
  const models=el('button','row rowBtn');models.type='button';
  models.appendChild(el('span','k',en?'Model provider':'模型服务商'));const mv=el('span','v');mv.innerHTML=CHEV;models.appendChild(mv);
  models.onclick=()=>openProviders();
  section(en?'Models':'模型').appendChild(models);

  const importRow=el('label','row rowBtn intImport');
  importRow.appendChild(el('span','k',en?'Import connection profile':'导入连接配置'));
  const iv=el('span','v');iv.appendChild(el('span',null,'JSON'));iv.insertAdjacentHTML('beforeend',CHEV);importRow.appendChild(iv);
  const upload=el('input');upload.type='file';upload.accept='.json,application/json';upload.className='intFile';
  upload.setAttribute('aria-label',en?'Import connection profile':'导入连接配置');importRow.appendChild(upload);
  section(en?'Connection profile':'连接配置').appendChild(importRow);

  const inputs={};
  for(const [name,spec] of Object.entries(MODULES)){
    const saved=config[name]||{},on=!!saved.url;
    const chip=el('span','intChip'+(on?' on':''),on?(en?'Enabled':'已启用'):(en?'Not set':'未配置'));
    const card=section(L([spec.zh[0],spec.en[0]]),chip);card.classList.add('intCard');
    card.appendChild(el('p','intDesc',L([spec.zh[1],spec.en[1]])));
    inputs[name]={};
    for(const field of spec.fields){
      const id='int_'+name+'_'+field,wrap=el('div','field'),label=el('label',null,L(FIELD[field]));label.htmlFor=id;
      const box=el('div','inputwrap'),input=el('input');input.id=id;input.type=field==='token'?'password':'text';
      input.autocomplete='off';input.spellcheck=false;input.setAttribute('autocapitalize','off');
      if(field==='url'){input.inputMode='url';input.placeholder=spec.scheme+'://'}
      input.value=field==='token'?'':(saved[field]||'');
      if(field==='token'&&saved.has_token)input.placeholder=en?'Saved (leave blank to retain)':'已保存（留空保留）';
      input.addEventListener('focus',()=>setTimeout(()=>input.scrollIntoView({block:'center',behavior:'smooth'}),250));   // keyboard (adjustResize) must not cover the field
      box.appendChild(input);wrap.appendChild(label);wrap.appendChild(box);card.appendChild(wrap);inputs[name][field]=input;
    }
    if(name==='pclink'){   // 显式公共中继: 确认风险后只填入表单, 仍需用户点保存
      const preset=el('button','intPreset',en?'Use the public GenericAgent relay':'使用 GenericAgent 公共中继');preset.type='button';
      preset.onclick=()=>gaModal({title:en?'Public relay':'公共中继',msg:L(PUBLIC_RELAY_NOTE),okText:en?'Fill in':'填入',onOk:()=>{
        inputs.pclink.url.value=PUBLIC_RELAY.url;inputs.pclink.token.value=PUBLIC_RELAY.token;
        error.classList.remove('bad');error.textContent=en?'Public relay filled in. Review, then Save to enable.':'已填入公共中继，确认后点保存才会启用。'}});
      card.appendChild(preset);
    }
  }
  const error=el('p','intErr');error.setAttribute('role','status');error.setAttribute('aria-live','polite');panel.appendChild(error);
  const acts=el('div','intActs'),save=el('button','btnPrimary',en?'Save':'保存');save.type='button';acts.appendChild(save);panel.appendChild(acts);

  upload.onchange=async()=>{
    try{
      const file=upload.files[0];if(!file)return;if(file.size>65536)throw Error('Profile exceeds 64 KiB');
      const values=parseProfile(JSON.parse(await file.text()),inputs);
      for(const [name,fields] of Object.entries(values))for(const [field,input] of Object.entries(inputs[name]))input.value=fields[field]||'';
      error.classList.remove('bad');error.textContent=en?'Review addresses and credentials, then Save to enable.':'请检查地址和凭据，点击保存后才启用。';
    }catch(e){error.classList.add('bad');error.textContent=String(e)}finally{upload.value=''}
  };
  save.onclick=()=>{
    const payload={};for(const [name,fields] of Object.entries(inputs))payload[name]=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.value]));
    try{const result=JSON.parse(GA.send('/integrations.save '+JSON.stringify(payload))||'{}');
      if(!result.ok){error.classList.add('bad');error.textContent=result.error||'Save failed';error.scrollIntoView({block:'center'});return}
      toast(en?'Saved':'已保存');if(window.PCLINK)PCLINK.refreshStatus();setvBack()}
    catch(e){error.classList.add('bad');error.textContent=String(e)}
  };
  setNav('integrationsPanel',en?'Optional modules':'可选组件');
  const target=focus&&inputs[focus]&&inputs[focus].url.closest('.card');
  if(target)(target.previousElementSibling||target).scrollIntoView({block:'start'});
}
window.openIntegrations=openIntegrations;
})();
