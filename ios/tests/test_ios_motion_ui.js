// iOS vertical sheet geometry, gesture decisions and floating-control gating; Android keeps its original thresholds.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const base='app/src/main/assets/ga_runtime/webui/';
const {app,extract}=require('./webui_source.cjs');
const pc=fs.readFileSync(base+'pclink.js','utf8');
const c={};vm.createContext(c);vm.runInContext(['iosNavFrame','iosSwipeCommits','iosSpeed'].map(n=>extract(app,n)).join('\n'),c);
const y=t=>Number(/translate3d\(0,(-?[\d.]+)px/.exec(t)[1]);
assert.deepEqual(c.iosNavFrame(0,800),c.iosNavFrame(-2,800));
assert.deepEqual(c.iosNavFrame(1,800),c.iosNavFrame(3,800));
assert.equal(y(c.iosNavFrame(0,800).upper),800);
assert.equal(y(c.iosNavFrame(1,800).upper),0);
assert.equal(c.iosNavFrame(1,800).dim,'brightness(0.920)');
assert.equal(c.iosNavFrame(0,800).dim,'brightness(1.000)');
for(let p=0.1;p<=1;p+=0.1){const a=c.iosNavFrame(p-0.1,800),b=c.iosNavFrame(p,800);
  assert(y(b.upper)<y(a.upper),'incoming page rises; horizontal displacement is always zero');
  assert(y(b.lower)<=0&&y(b.lower)>=-10,'underlying page stays in place with bounded depth');}

assert.equal(c.iosSwipeCommits(.2,0),false);assert.equal(c.iosSwipeCommits(.4,0),true);
assert.equal(c.iosSwipeCommits(.1,.5),true,'a fling completes even when short');
assert.equal(c.iosSwipeCommits(.6,-.3),false,'moving back toward the edge cancels');
assert.equal(c.iosSwipeCommits(.3,0,.25),true);assert.equal(c.iosSwipeCommits(.2,0,.25),false);
const speed=c.iosSpeed(0,0);speed.move(3,4);assert.equal(speed.at(5),0,'samples closer than a frame are ignored');
speed.move(32,16);assert.equal(speed.at(20),2);assert.equal(speed.at(200),0,'a held finger has no release speed');

function scrollNav(ios,{scrollTop,scrollHeight,clientHeight,empty=false}){
  const el=()=>{const classes=new Set();return {hidden:false,classList:{toggle:(k,on)=>on?classes.add(k):classes.delete(k),remove:k=>classes.delete(k),contains:k=>classes.has(k)}}};
  const s={chat:{scrollTop,scrollHeight,clientHeight},_snav:el(),_snUp:el(),_snDown:el(),pinned:false,isIOSClient:()=>ios,emptyEl:empty?{}:null};
  const update=app.slice(app.indexOf('function updateScrollNav('),app.indexOf('\nif(_snUp)'));
  vm.createContext(s);vm.runInContext(extract(app,'nearBottom')+'\n'+update,s);s.updateScrollNav();
  return {up:!s._snUp.hidden,down:!s._snDown.hidden,on:s._snav.classList.contains('on')};
}
assert.deepEqual(scrollNav(true,{scrollTop:0,scrollHeight:1100,clientHeight:700}),{up:false,down:true,on:true},'iOS: away from bottom is enough');
assert.deepEqual(scrollNav(true,{scrollTop:2000,scrollHeight:4000,clientHeight:700}),{up:false,down:true,on:true},'iOS never shows scroll-to-top');
assert.deepEqual(scrollNav(true,{scrollTop:3250,scrollHeight:4000,clientHeight:700}),{up:false,down:false,on:false},'hidden at the bottom');
assert.deepEqual(scrollNav(true,{scrollTop:0,scrollHeight:1100,clientHeight:400,empty:true}),{up:false,down:false,on:false},'iOS start page keeps no return control while the keyboard shortens the scroller');
assert.deepEqual(scrollNav(false,{scrollTop:0,scrollHeight:1100,clientHeight:700}),{up:false,down:false,on:false},'Android keeps the 600px threshold');
assert.deepEqual(scrollNav(false,{scrollTop:2000,scrollHeight:4000,clientHeight:700}),{up:true,down:true,on:true});

function pcDown(ios,box){const dn={hidden:false,classList:{contains:()=>false}};const s={IS_IOS:ios,document:{getElementById:()=>dn}};
  vm.createContext(s);vm.runInContext(extract(pc,'pcSyncDown'),s);s.pcSyncDown({querySelector:()=>null,...box});return !dn.hidden}
assert.equal(pcDown(true,{scrollTop:0,scrollHeight:1100,clientHeight:700}),true);
assert.equal(pcDown(false,{scrollTop:0,scrollHeight:1100,clientHeight:700}),false);
assert.equal(pcDown(true,{scrollTop:400,scrollHeight:1100,clientHeight:700}),false);
assert.equal(pcDown(true,{scrollTop:0,scrollHeight:1100,clientHeight:400,querySelector:()=>({})}),false,'computer start page keeps no return-to-latest control');

assert(/if\(IS_IOS\)\{[^}]*insertBefore\(b,document\.getElementById\('hdrMoreBtn'\)\)\}/.test(pc),'iOS switch lives in the header');
assert(/else document\.body\.appendChild\(b\);/.test(pc),'Android keeps the floating switch');
console.log('PASS: vertical sheet frames clamp and preserve depth, swipe completion uses distance and release speed, and only iOS gets the centred return-to-latest control with the header switch.');
