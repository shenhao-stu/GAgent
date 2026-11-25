// iOS settings sheet and start page redesign: trailing 完成 capsule instead of a leading X,
// grouped device connections, VPN-aware proxy detection, failed-conversation red dot, and readable native controls.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base='app/src/main/assets/ga_runtime/webui/';
const {app,extract}=require('./webui_source.cjs');
const css=['app.css','ios_settings.css'].map(f=>fs.readFileSync(base+f,'utf8')).join('\n');
const bridge=fs.readFileSync(base+'ios_settings.js','utf8');

// Sidebar: every conversation state has a visible dot; failed is red, interrupted is a ring.
assert(/\.dwItem \.cst\.failed i\{background:var\(--err\)\}/.test(css),'failed conversations get a red dot');
assert(/\.dwItem \.cst\.interrupted i\{[^}]*box-shadow:inset 0 0 0 1\.5px var\(--txt2\)/.test(css),'stopped conversations get a ring');

// Settings bar: the sheet closes from a trailing capsule; the leading chevron exists only on pushed pages.
const init=extract(app,'iosConfigureSettingsChrome');
const labels=extract(app,'initIOSNavigation');
assert(/done\.id='iosSetvDone'/.test(init)&&/done\.onclick=closeSettings/.test(init),'a Done capsule dismisses the sheet');
assert(/trailing\.append\(\$\('setvTest'\),done\)/.test(init),'settings actions share the trailing group');
const show=extract(app,'iosSettingsDidShow');
assert(/back\.hidden=root/.test(show),'the leading button is hidden at the root page');
assert(!/M6 6l12 12/.test(show),'no X glyph remains');
assert(/\.iosApp \.setbar>\.iconbtn:first-child\[hidden\]\{display:none\}/.test(css));
assert(/\.iosApp \.iosBarDone,[^}]*backdrop-filter:var\(--ios-bar-filter/.test(css),'navigation controls share glass material');
const present=extract(app,'iosPresentView');
assert(/#setv\.on \.setbar>\.iconbtn:not\(\[hidden\]\),#setv\.on \.iosBarDone/.test(present),'focus return skips the hidden leading button');

// Connections card: groups iPhone control, PC Link, and local proxy switch at the top of homePanel.
assert(/section\.id='iosConnections'/.test(bridge)&&/entry\.id='iosBoardSetup'/.test(bridge),'connections section mounts iPhone control');

// Android retains its legacy manual detection action.
function detect(opts){
  const log={sends:[],toasts:[],modal:null,proxy:''};
  const s={$:id=>id==='toast'?{classList:{remove(){log.toastCleared=true}}}:null,toast:m=>log.toasts.push(m),t:k=>k,isIOSClient:()=>opts.ios,LS:{set(k,v){log.proxy=v}},refreshProxyVal(){},gaModal:o=>{log.modal=o},
    setTimeout:(f)=>f(),GA:{send:c=>{log.sends.push(c);return c.startsWith('/detectproxy')?JSON.stringify({proxy:opts.found||''}):''},networkProxy:opts.native?()=>JSON.stringify(opts.native):undefined}};
  vm.createContext(s);vm.runInContext('var globalProxy="";'+extract(app,'detectProxy')+';detectProxy()',s);
  return log;
}
let r=detect({ios:false,native:{proxy:'http://127.0.0.1:1082',vpn:true}});
assert.equal(r.sends[0],'/detectproxy','Android keeps the port probe only');assert.equal(r.toasts[1],'t_proxyNone');
assert(/networkProxy:\s*nat\('networkProxy'\)/.test(fs.readFileSync('ios/GAgent/ios_bridge.js','utf8')));
assert(/iosDone:'完成'/.test(labels));

// Home layout and suggestion behavior are covered by the browser viewport matrix.
assert(/prefers-reduced-transparency:reduce\)\{[\s\S]*?\.iosApp \.heroChip,\.iosApp \.iosPhoneCard\{background:var\(--surface\)/.test(css));
assert(/\.iosApp #setv \.card\{[^}]*border-radius:24px/.test(css)&&!/\.iosApp #homePanel \.card\{/.test(css),'one card radius for the whole sheet');
console.log('PASS: trailing Done capsule and hidden root chevron, grouped connections, VPN-aware proxy detection, failed red dot, native controls with reduced-transparency fallback.');
