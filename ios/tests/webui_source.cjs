// Extract a single real declaration, regardless of which script or adjacent declarations contain it.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const base=path.resolve(__dirname,'../../app/src/main/assets/ga_runtime/webui');
const app=['ios_ui.js','ios_settings.js','app.js'].map(f=>fs.readFileSync(path.join(base,f),'utf8')).join('\n');
function extract(source,name){
  const start=source.indexOf('function '+name+'(');
  if(start<0)throw Error('Missing function: '+name);
  for(let i=source.indexOf('}',start);i>=0;i=source.indexOf('}',i+1)){
    const candidate=source.slice(start,i+1);
    try{new vm.Script('('+candidate+')');return candidate}catch(e){if(!(e instanceof SyntaxError))throw e}
  }
  throw Error('Incomplete function: '+name);
}
module.exports={app,extract};
