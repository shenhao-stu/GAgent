// Run from repository root: node ios/tests/test_ios_provider_ui.js
// Provider logos and connection errors on iOS: pure rules, run against the shipped source.
const vm=require('node:vm'),assert=require('node:assert/strict');
const {app,extract}=require('./webui_source.cjs');
function rules(ios){
  const context={isIOSClient:()=>ios};vm.createContext(context);
  vm.runInContext(['_brandMatch','brandKey','iosConnectionReason'].map(name=>extract(app,name)).join('\n'),context);
  return context;
}

// A logo names the maker of the model. On iOS the protocol of the endpoint never supplies one.
const ios=rules(true);
for(const [provider,model,type,brand] of [
  ['Stepfun','step-5-preview','claude','step'],
  ['Stepfun','stepaudio-2.5-asr','claude','step'],        // seen on the device with Claude's logo
  ['','stepaudio-2.5-tts','claude','step'],
  ['Stepfun','newly-listed-model','claude','step'],       // an id nobody knows yet: the provider's own brand
  ['My Relay','newly-listed-model','claude','unknown'],
  ['My Relay','newly-listed-model','oai','unknown'],
  ['claude-native','newly-listed-model','claude','unknown'],   // the names the editor gives an unnamed provider
  ['gpt-native','newly-listed-model','oai','unknown'],
  ['My Relay','claude-opus-5','oai','claude'],
  ['My Relay','gpt-6.1-sol','claude','openai'],
  ['',undefined,undefined,'unknown']])assert.equal(ios.brandKey(provider,model,type),brand,JSON.stringify([provider,model,type]));
// Android keeps its rule: the protocol decides when nothing else does.
const android=rules(false);
assert.equal(android.brandKey('My Relay','newly-listed-model','claude'),'claude');
assert.equal(android.brandKey('My Relay','newly-listed-model','oai'),'openai');
assert.equal(android.brandKey('My Relay','newly-listed-model'),'generic');

// A failed request is reported in the service's own words, without what Python and JSON wrap around them.
const pool="HTTPSConnectionPool(host='api.example', port=443): Max retries exceeded with url: /v1/models ";
for(const [error,reason] of [
  ["ConnectTimeout: "+pool+"(Caused by ConnectTimeoutError(<urllib3.connection.HTTPSConnection object at 0x10f3a3a10>, 'Connection to api.example timed out. (connect timeout=10)'))",
   'ConnectTimeout: Connection to api.example timed out. (connect timeout=10)'],
  // The backend cuts errors at 200 characters, here inside the parenthesis.
  ["ConnectTimeout: "+pool+"(Caused by ConnectTimeoutError(<urllib3.connection.HTTPSConnection object at 0x10f3a3a10>, 'Connection to api.example timed out. (conn",
   'ConnectTimeout: Connection to api.example timed out.'],
  ["ConnectionError: "+pool+"(Caused by NameResolutionError(\"<urllib3.connection.HTTPSConnection object at 0x1100>: Failed to resolve 'api.example' ([Errno 8] nodename nor servname provided, or not known)\"))",
   "ConnectionError: Failed to resolve 'api.example' ([Errno 8] nodename nor servname provided, or not known)"],
  ["SSLError: "+pool+"(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:1006)')))",
   'SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:1006)'],
  ["{'message': 'Incorrect API key provided', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_api_key'}",'Incorrect API key provided'],
  ["{'message': \"You didn't provide an API key.\", 'type': 'invalid_request_error'}","You didn't provide an API key."],
  ['HTTP 401: {"error":{"message":"Incorrect API key provided","type":"invalid_request_error"}}','HTTP 401 Incorrect API key provided'],
  ['HTTP 404: <html><head><title>404 Not Found</title></head><body>','HTTP 404'],
  ['HTTP 502: Bad Gateway','HTTP 502: Bad Gateway'],
  ['未返回模型 (HTTP 200)','未返回模型 (HTTP 200)'],
  ["ReadTimeout: HTTPSConnectionPool(host='api.example', port=443): Read timed out. (read timeout=25)","ReadTimeout: HTTPSConnectionPool(host='api.example', port=443): Read timed out. (read timeout=25)"],
  ['x'.repeat(300),'x'.repeat(159)+'…'],
  ['',''],[undefined,'']])assert.equal(ios.iosConnectionReason(error),reason);
console.log('PASS: iOS logos name the maker of a model and leave Android\'s rule alone; connection errors are reported without their wrapping.');
