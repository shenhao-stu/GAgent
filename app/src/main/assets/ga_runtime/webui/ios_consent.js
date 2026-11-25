// Durable consent is owned by the engine; the view only requests a decision.
let _iosNoticeSeen=false,_iosConsentCheckPending=false;
function iosConsentState(){try{const s=JSON.parse(GA.send('/ios.consent.status')||'{}');return s&&s.ok?s:{ok:false}}catch(e){return {ok:false}}}
function iosRefreshConsent(onResult,isActive=()=>true,providerIds=null){
  const finish=r=>{if(isActive())onResult(r&&r.ok?r:{ok:false})};
  let job;try{job=JSON.parse(GA.send('/ios.consent.refresh'+(providerIds===null?'':' '+JSON.stringify({providerIds})))||'{}').job}catch(e){}
  if(!job){finish({ok:false});return null}
  return jobPoll((cont,stop)=>{
    if(!isActive()){stop();return}
    let r;try{r=JSON.parse(GA.send('/jobresult '+job)||'{}');if(r.pending){cont();return}r=JSON.parse(r.result||'{}')}catch(e){r={ok:false}}
    finish(r);
  },{interval:400,delay:250,maxTries:150,onTimeout:()=>finish({ok:false})});
}
function iosSelectedReceivers(state){
  const names=isAuto()?foNos(mkMixins.find(m=>m.name===active.auto)||foCfg):[];
  const selected=isAuto()?providers.filter(p=>p.enabled!==false&&names.includes(p.name)):[curProvider()];
  const ids=selected.filter(Boolean).map(p=>(state.providerIds||{})[p.name]).filter(Boolean);
  return ids.length?(state.receivers||[]).filter(r=>ids.includes(r.providerId)):null;
}
function iosSelectedUnavailable(state){const rs=iosSelectedReceivers(state);return !!(rs&&rs.length&&rs.every(r=>r.unavailable))}
function iosSelectedNeedsRefresh(state){const rs=iosSelectedReceivers(state);return rs?rs.some(r=>r.needsRefresh):!!state.needsRefresh}
function iosSelectedAccepted(state){const rs=iosSelectedReceivers(state);return rs?!!state.pcAccepted&&rs.length>0&&rs.filter(r=>!r.unavailable).every(r=>r.accepted):!!state.accepted}
function iosEnsureDataConsent(retry,kind){
  const s=iosConsentState();
  if(!s.ok){toast(t('iosConsentNotReady'));return false}
  const draft=inp.value,convo=curConvo,atts=JSON.stringify(pendingAtts),selection=JSON.stringify(active);
  const resume=()=>{if(kind==='pc'||(inp.value===draft&&curConvo===convo&&JSON.stringify(pendingAtts)===atts&&JSON.stringify(active)===selection))retry()};
  if(kind!=='pc'&&(iosSelectedNeedsRefresh(s)||iosSelectedUnavailable(s))){
    if(!_iosConsentCheckPending){
      _iosConsentCheckPending=true;
      const rs=iosSelectedReceivers(s);
      iosRefreshConsent(next=>{
        _iosConsentCheckPending=false;
        if(!next.ok||iosSelectedUnavailable(next)){const failed=(iosSelectedReceivers(next)||[]).find(r=>r.unavailable&&r.disclosureError);toast(failed?failed.disclosureError:t(next.ok?'iosDisclosureUnavailable':'iosConsentNotReady'));return}
        resume();
      },()=>true,rs?[...new Set(rs.map(r=>r.providerId))]:null);
    }
    return false;
  }
  if(kind==='pc'?s.pcAccepted:iosSelectedAccepted(s))return true;
  const rs=kind==='pc'?null:iosSelectedReceivers(s);
  showIOSDataConsent(resume,false,null,rs?[...new Set(rs.map(r=>r.providerId))]:null);return false;
}
function showIOSDataConsent(onAgree,manage,onDecline,providerIds=null){
  iosPrepareModal();
  const mask=$('modalMask'),card=$('modalCard');let state=iosConsentState(),loading=true,closed=false,poll=null;
  if(providerIds)state={...state,receivers:(state.receivers||[]).filter(r=>providerIds.includes(r.providerId))};
  card.className='modalCard privacyCard';
  card.innerHTML='<div class="pcHead"><span class="iosPrivacySymbol" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 8 3v5c0 5-5 9-8 10-3-1-8-5-8-10V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg></span><h4></h4><p class="pcSub"></p></div><div class="pcBody"></div><div class="pcFoot"></div>';
  card.querySelector('h4').textContent=t('iosSharingTitle');card.querySelector('.pcSub').textContent=t('iosSharingSub');
  const body=card.querySelector('.pcBody'),foot=card.querySelector('.pcFoot');
  const para=(txt,parent=body)=>{for(const text of txt.split('\n')){const p=document.createElement('p');p.textContent=text;parent.appendChild(p)}};
  const section=(title)=>{const s=document.createElement('section');s.className='iosDisclosureSection';
    const h=document.createElement('h5');h.textContent=title;s.appendChild(h);body.appendChild(s);return s};
  const render=()=>{body.innerHTML='';const recipients=section(t('iosRecipients'));
    const recs=Array.isArray(state.receivers)?state.receivers:[];
    if(!recs.length)para(t('iosNoProvider'),recipients);
    // Several models can share one recipient; the disclosure describes recipients, not model routing.
    const seen=new Set();recs.forEach(r=>{const key=JSON.stringify([r.providerId,r.recipients,r.unavailable]);if(seen.has(key))return;seen.add(key);
      const card=document.createElement('div');card.className='iosRecipientCard';recipients.appendChild(card);
      const provider=Object.entries(state.providerIds||{}).find(([,id])=>id===r.providerId)?.[0];
      const declared=(r.recipients||[]).join(' / ');
      if(provider){const name=document.createElement('strong');name.textContent=provider;card.appendChild(name)}
      if(declared)para(declared,card);
      else if(!provider)para(t('iosNoProvider'),card);
      if(r.unavailable)para(t('iosDisclosureUnavailable'),card);
    });
    for(const [heading,key] of [['iosSharedContent','iosSharingAI'],['iosOptionalComputer','iosSharingPC'],['iosOptionalPermissions','iosSharingSensors'],
      ['iosDataStorage','iosSharingRetention'],['iosDataChoice','iosSharingChoice']])para(t(key),section(t(heading)));
    if(!state.ok&&!loading)para(t('iosConsentNotReady'));
    body.appendChild(policy);if(revoke){revoke.hidden=!state.pcAccepted;body.appendChild(revoke)}
  };
  const isOpen=()=>!closed&&mask.classList.contains('on')&&card.querySelector('.pcFoot')===foot;
  const close=()=>{closed=true;if(poll)poll.stop();mask.classList.remove('on');card.className='modalCard';_iosNoticeSeen=true};
  const kinds={primary:'pcAgree',secondary:'cancel',link:'iosConsentLink',destructive:'iosConsentLink danger'};
  const button=(id,label,fn,kind='secondary',parent=foot)=>{const b=document.createElement('button');b.type='button';b.id=id;b.textContent=label;b.className=kinds[kind];b.onclick=fn;parent.appendChild(b);return b};
  const policy=button('iosPrivacyPolicy',t('iosFullPolicy'),()=>GA.openUrl('https://github.com/shenhao-stu/GAgent/blob/main/PRIVACY.md'),'link',body);
  const agree=button('iosConsentAgree',t('iosConsentAgree'),()=>{
    if(loading)return;
    if(!state.ok){refresh();return}
    if(manage&&state.accepted){close();return}
    try{const r=JSON.parse(GA.send('/ios.consent '+JSON.stringify({version:state.version,providerSignature:state.providerSignature,accepted:true,...(providerIds===null?{}:{providerIds})}))||'{}');
      if(!r.ok||!r.accepted){refresh();return}
      close();if(onAgree)setTimeout(onAgree,0);
    }catch(e){toast(t('iosConsentNotReady'))}
  },'primary');
  const decline=button('iosConsentDecline',manage?t('close'):t('iosDecline'),()=>{close();if(onDecline)onDecline()});
  const revoke=manage?button('iosConsentRevoke',t('iosRevoke'),()=>{
    try{const r=JSON.parse(GA.send('/ios.consent '+JSON.stringify({accepted:false}))||'{}');if(!r.ok)throw Error();close();toast(t('iosRevoked'))}catch(e){toast(t('iosConsentNotReady'))}
  },'destructive',body):null;
  const finish=next=>{if(!isOpen())return;state=next;loading=false;render();agree.disabled=false;
    decline.hidden=!!(manage&&state.ok&&state.accepted);
    agree.textContent=t(!state.ok?'iosRetryDisclosure':manage&&state.accepted?'iosDone':'iosConsentAgree')};
  const refresh=()=>{
    loading=true;agree.disabled=true;agree.textContent=t('loading');
    poll=iosRefreshConsent(finish,isOpen,providerIds);
  };
  mask.onclick=e=>{if(e.target===mask&&manage)close()};card.onclick=e=>e.stopPropagation();mask.classList.add('on');
  render();refresh();
}
