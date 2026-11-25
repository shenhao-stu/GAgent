// Presentation consumes the existing aggregate. No storage, requests or alternate counting rules.
function iosStatIcon(kind){
  const paths={chats:'<path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 3v-3H3V6a2 2 0 0 1 2-2Z"/>',
    messages:'<path d="M5 6h14M5 12h14M5 18h9"/>',input:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    output:'<path d="M12 16V3m-5 5 5-5 5 5M4 17v4h16v-4"/>',activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    models:'<path d="M5 20v-7m7 7V4m7 16V9"/>',empty:'<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8 15v-3m4 3V9m4 6v-5"/>'};
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[kind]+'</svg>';
}
function prepareIOSStats(){
  const panel=$('statsPanel');if(panel.dataset.iosStats)return;panel.dataset.iosStats='true';
  Object.assign(I18N.zh,{iosStatsActivity:'对话活动',iosStatsModels:'模型用量',iosStatsModelHint:'按输入与输出 token 总量排序；条形长度采用同一比例。',
    iosStatsEmpty:'还没有模型用量',iosStatsEmptyHint:'完成一次模型对话后，用量会显示在这里。',iosStatsHeatHint:'每格代表一天。点选查看明细，左右滑动查看全年。',
    iosStatsCacheHint:'缓存命中率 = 缓存读取 ÷ 输入 token。输入用量已包含缓存读取。',iosStatsTotal:'合计',iosStatsInput:'输入',iosStatsOutput:'输出'});
  Object.assign(I18N.en,{iosStatsActivity:'Conversation activity',iosStatsModels:'Model usage',iosStatsModelHint:'Sorted by input + output tokens. Bars share the same scale.',
    iosStatsEmpty:'No model usage yet',iosStatsEmptyHint:'Usage will appear after a model conversation.',iosStatsHeatHint:'One square per day. Tap for details; scroll to explore the year.',
    iosStatsCacheHint:'Cache hit rate = cache reads ÷ input tokens. Input already includes cache reads.',iosStatsTotal:'Total',iosStatsInput:'Input',iosStatsOutput:'Output'});
  const heading=key=>{const e=document.createElement('div');e.className='secLbl';const s=el('span','',e);s.dataset.i18n=key;s.textContent=t(key);return e};
  const note=key=>{const e=document.createElement('p');e.className='hint';e.dataset.i18n=key;e.textContent=t(key);return e};
  const heat=panel.querySelector('.heatCard'),heatHead=heat.previousElementSibling,overview=$('statGrid').previousElementSibling.previousElementSibling;
  const modelHead=$('modelStats').previousElementSibling;
  heatHead.querySelector('span').dataset.i18n='iosStatsActivity';heatHead.querySelector('span').textContent=t('iosStatsActivity');
  modelHead.querySelector('span').dataset.i18n='iosStatsModels';modelHead.querySelector('span').textContent=t('iosStatsModels');
  heatHead.querySelector('span').insertAdjacentHTML('beforebegin',iosStatIcon('activity'));
  modelHead.querySelector('span').insertAdjacentHTML('beforebegin',iosStatIcon('models'));
  overview.remove();panel.prepend(heading('overview'),$('statRanges'),$('statGrid'));
  $('statGrid').after(note('iosStatsCacheHint'));heat.after(note('iosStatsHeatHint'));
  modelHead.after(note('iosStatsModelHint'));
}
function renderIOSStatSummary(aggregate){
  const A=aggregate,g=$('statGrid');g.innerHTML='';
  const metrics=[[A.convos,'statConvos','chats'],[A.msgs,'statMsgs','messages'],[humanTok(A.ti),'statTokIn','input'],[humanTok(A.to),'statTokOut','output'],
    [A.steps,'statSteps'],[humanTok(A.cr),'statCacheRead'],[humanTok(A.cw),'statCacheWrite'],[_hitRate(A.cr,A.ti),'statCacheHit']];
  for(const [value,key,icon] of metrics){
    const cell=el('div',icon?'statCard':'statDetail',g),label=el('div','statLbl',cell);
    if(icon)label.innerHTML=iosStatIcon(icon);const text=el('span','',label);text.textContent=t(key);
    const number=el('div','statNum',cell);number.textContent=value;
  }
  $('statRanges').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.classList.contains('on'))));
  const ms=$('modelStats');ms.innerHTML='';
  const models=[...A.byModel.entries()].sort((a,b)=>(b[1].ti+b[1].to)-(a[1].ti+a[1].to));
  const max=Math.max(0,...models.map(([,v])=>v.ti+v.to));
  if(!models.length){
    const empty=el('div','iosStatsEmpty',ms);empty.innerHTML=iosStatIcon('empty');
    el('strong','',empty).textContent=t('iosStatsEmpty');el('p','',empty).textContent=t('iosStatsEmptyHint');return;
  }
  for(const [name,v] of models){
    const row=el('div','iosModelUsage',ms),head=el('div','iosModelHead',row);
    const logo=el('span','iosModelGlyph',head);logo.setAttribute('aria-hidden','true');logo.innerHTML=modelGlyph(name);
    el('span','iosModelName',head).textContent=name;
    el('span','iosModelTotal',head).textContent=humanTok(v.ti+v.to)+' tokens';
    const track=el('div','iosModelTrack',row);track.setAttribute('role','img');
    track.setAttribute('aria-label',name+' · '+t('iosStatsInput')+' '+v.ti+' · '+t('iosStatsOutput')+' '+v.to+' tokens');
    const bar=el('div','iosModelBar',track);bar.style.width=(max?(v.ti+v.to)/max*100:0)+'%';
    el('span','iosModelInput',bar).style.flexGrow=v.ti;el('span','iosModelOutput',bar).style.flexGrow=v.to;
    const values=el('div','iosModelValues',row);
    el('span','',values).textContent=t('iosStatsInput')+' '+humanTok(v.ti);
    el('span','',values).textContent=t('iosStatsOutput')+' '+humanTok(v.to);
    el('div','iosModelMeta',row).textContent=v.n+t('unitMsgs')+' · '+v.steps+' '+t('steps');
  }
}
