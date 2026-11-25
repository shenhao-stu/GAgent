// iOS chat polish: compact artifact chips, live system appearance, quiet focus return; Android keeps full names.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base='app/src/main/assets/ga_runtime/webui/';
const {app,extract}=require('./webui_source.cjs');
const css=['app.css','ios_settings.css'].map(f=>fs.readFileSync(base+f,'utf8')).join('\n');
const bridge=fs.readFileSync(base+'ios_settings.js','utf8');

const c={};vm.createContext(c);vm.runInContext(extract(app,'shortFileName'),c);
assert.equal(c.shortFileName('3a5f15c320c24141aeee008ec1cfb.jpg'),'3a5f15…cfb.jpg');
assert.equal(c.shortFileName('report.pdf'),'report.pdf','short names stay whole');
assert.equal(c.shortFileName('微信群聊截图二〇二六年十月.png'),'微信群聊截图…年十月.png');
assert.equal(c.shortFileName('archive.backup.tar.gz'),'archiv…tar.gz','the last short suffix is kept as the extension');
assert.equal(c.shortFileName('README_without_extension'),'README…ion');

function chips(ios){
  const made=[];
  const el=(tag,cls,parent)=>{const e={cls,innerHTML:'',attrs:{},children:[],setAttribute(k,v){this.attrs[k]=v}};if(parent)parent.children.push(e);made.push(e);return e};
  const s={el,t:k=>k,_escd:x=>x,fileIcon:()=>'',fileKind:()=>'image',_enc:x=>x,openFilePreview(){},isIOSClient:()=>ios};
  vm.createContext(s);vm.runInContext(extract(app,'renderArtifacts')+'\n'+extract(app,'shortFileName'),s);
  s.renderArtifacts([{path:'iphone_screens/3a5f15c320c24141aeee008ec1cfb.jpg',name:'3a5f15c320c24141aeee008ec1cfb.jpg'}],{children:[]});
  return made.find(e=>e.cls==='artChip');
}
const ios=chips(true),android=chips(false);
assert(ios.innerHTML.includes('3a5f15…cfb.jpg'));assert.equal(ios.title,'3a5f15c320c24141aeee008ec1cfb.jpg');
assert.equal(ios.attrs['aria-label'],'3a5f15c320c24141aeee008ec1cfb.jpg','VoiceOver reads the full name');
assert(android.innerHTML.includes('3a5f15c320c24141aeee008ec1cfb.jpg'),'Android keeps the full name');
assert(/\.iosApp \.artChip\{[^}]*max-width:calc\(50% - 3px\)/.test(css),'at least two chips share a row on iOS');

const init=extract(app,'initIOSNavigation');
assert(/matchMedia\('\(prefers-color-scheme: dark\)'\)\.addEventListener\('change',\(\)=>\{\s*if\(theme!=='system'\)return;applyTheme\(\)/.test(init),
  'a system appearance change re-applies the follow-system theme without a relaunch');
assert(/new ResizeObserver\(\(\)=>\{[^}]*updateScrollNav\(\)\}\)\.observe\(chat\)/.test(init),
  'a keyboard closing over a short chat hides the return-to-latest control without a scroll event');
const present=extract(app,'iosPresentView');
assert(present.indexOf('next.dataset.iosQuietFocus')>=0&&present.indexOf('next.dataset.iosQuietFocus')<present.indexOf('next.focus('),
  'focus returned after closing is marked quiet before it moves');
assert(/\.iosApp \[data-ios-quiet-focus\]:focus-visible\{outline:none\}/.test(css));
assert(/byI18n\('proxyHint'\)\?\.remove\(\)/.test(bridge),'iOS settings drop the proxy footnote');
assert(/\.iosApp #setv \[id\$="Panel"\]>\.secLbl:first-child\{margin-top:6px\}/.test(css),
  'only a panel\'s first section label is tightened, not the first label inside an injected section');
console.log('PASS: iOS artifact chips use middle-ellipsis names with full accessible names, follow-system tracks appearance changes, returned focus is quiet, and settings labels align.');
