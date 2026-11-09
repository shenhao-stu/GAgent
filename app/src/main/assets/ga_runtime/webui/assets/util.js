function _escd(s){return String(s==null?'':s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]))}   // 含双引号: 调用方有把结果放进 "..." 属性位的(aria-label 等), 文本位多转无害
function jobPoll(cmd,opts){
  opts=opts||{};
  const interval=opts.interval;
  const delay=opts.delay!=null?opts.delay:interval;
  const timeout=opts.timeout||0;
  const maxTries=opts.maxTries||0;
  const onTimeout=opts.onTimeout||function(){};
  const t0=Date.now();
  let tries=0,stopped=false,timer=null;
  function stop(){stopped=true;if(timer)clearTimeout(timer)}
  function sched(ms){if(ms===0)tick();else timer=setTimeout(tick,ms)}
  function cont(){
    tries++;
    if(maxTries&&tries>maxTries){stopped=true;onTimeout();return}
    if(!stopped)sched(interval);
  }
  function tick(){
    if(stopped)return;
    if(timeout&&(Date.now()-t0)>timeout){stopped=true;onTimeout();return}
    cmd(cont,stop);
  }
  sched(delay);
  return {stop:stop};
}
