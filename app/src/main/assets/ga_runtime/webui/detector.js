/* Local detector import and an actual on-device screenshot/inference check. */
Object.assign(I18N.zh,{localDetector:'本地图标识别'});
Object.assign(I18N.en,{localDetector:'Local icon detection'});
function closeDetector(){const o=document.getElementById('detectorDialog');if(!o)return;const back=o._returnFocus;o.remove();if(back&&back.isConnected)try{back.focus({preventScroll:true})}catch(e){}}
function openDetector(){
  const en=lang==='en';
  closeDetector();   // 单实例: 重复打开替换旧框, 不叠出重复 id
  const overlay=document.createElement('div');overlay.id='detectorDialog';overlay._returnFocus=document.activeElement;
  overlay.onclick=e=>{if(e.target===overlay)closeDetector()};
  const card=document.createElement('div');card.className='modalCard';
  card.setAttribute('role','dialog');card.setAttribute('aria-modal','true');card.setAttribute('aria-label',t('localDetector'));
  const title=document.createElement('h3');title.textContent=t('localDetector');card.appendChild(title);
  const hint=document.createElement('p');hint.textContent=en?'OCR is included. Import your compatible 21-class Android UI ONNX model to detect icons without text. No account or cloud service is used. Only import a trusted model under its applicable license.':'已内置 OCR。导入你持有的兼容 21 类 Android UI ONNX 模型，可补全无文字图标检测；无需账号或云服务。仅导入来源可信且符合适用许可的模型。';card.appendChild(hint);
  const state=document.createElement('p');state.id='detectorState';card.appendChild(state);
  const file=document.createElement('input');file.type='file';file.accept='*/*';file.setAttribute('aria-label',en?'Import ONNX model':'导入 ONNX 模型');card.appendChild(file);
  const buttons=document.createElement('div');buttons.className='modalBtns';card.appendChild(buttons);
  const test=document.createElement('button');test.className='ok';test.textContent=en?'Test current screen':'检测当前屏幕';buttons.appendChild(test);
  const close=document.createElement('button');close.className='cancel';close.textContent=en?'Close':'关闭';close.onclick=closeDetector;buttons.appendChild(close);
  overlay.appendChild(card);document.body.appendChild(overlay);
  function display(r){state.textContent=!r.ok?(r.error||'Error'):(r.installed?(en?'Icon model installed':'图标模型已安装'):(en?'OCR only — import an icon model':'当前仅 OCR，请导入图标模型'));
    if(r.sha256)state.textContent+=' · SHA-256 '+r.sha256;
    if(r.icons!==undefined)state.textContent+=(en?' · Icons: ':' · 图标：')+r.icons+(en?' · Text: ':' · 文字：')+r.text+' · '+r.width+'×'+r.height+' · '+r.elapsed_ms+' ms';}
  async function call(command){
    let r=JSON.parse(GA.send(command)||'{}');
    if(!r.job)return r;
    const id=r.job,deadline=Date.now()+85000;
    while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,400));r=JSON.parse(GA.send('/jobresult '+id)||'{}');if(r.pending===false)return typeof r.result==='string'?JSON.parse(r.result):r.result;}
    throw Error(en?'Check timed out; reopen to inspect installed state':'等待超时，请重新打开检查安装状态');
  }
  async function work(action){file.disabled=test.disabled=true;state.textContent=en?'Working…':'处理中…';try{display(await action())}catch(e){state.textContent=String(e)}finally{file.disabled=test.disabled=false;file.value=''}}
  file.onchange=()=>{const selected=file.files[0];if(!selected)return;
    work(async()=>{if(!selected.name.toLowerCase().endsWith('.onnx')||selected.size>32*1024*1024)throw Error(en?'Choose an ONNX file up to 32 MiB':'请选择不超过 32 MiB 的 ONNX 文件');
      const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(selected)});
      const path=GA.saveUpload(selected.name,data);if(!path||path.startsWith('ERROR:'))throw Error(path||'Upload failed');
      return call('/detector.install '+path);});};
  test.onclick=()=>work(()=>call('/detector.test'));
  call('/detector.status').then(display).catch(e=>{state.textContent=String(e)});
}
