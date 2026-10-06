// Execute the unchanged GUI bootstrap and full pinned SerialCLI class.
// Only USB delivery and host/application time are simulated. Production GPS
// timing and optional boot-inventory metadata operation costs control readyMs.
// The response uses the actual production CR parser and CommonCLI time branch.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {setImmediate as turn} from 'node:timers/promises';

const firmware=spawn(process.argv[4],[],{stdio:['pipe','pipe','inherit']});
const readyMs=Number(process.argv[5]);
const preconnectIdleMs=Number(process.argv[6]||0);
let output, pending;
createInterface({input:firmware.stdout}).on('line',line=>{
  if(line.startsWith('DATA ')){
    const bytes=Buffer.from(line.slice(5),'hex');
    for(const byte of bytes)output.enqueue(new Uint8Array([byte]));
  }else if(line==='DONE'){
    const operation=pending;pending=null;operation.resolve();
  }
});
firmware.on('exit',code=>{if(pending)pending.reject(Error('Firmware exited '+code));});
function device(command){
  assert(!pending,'Peripheral operations must be serialized');
  return new Promise((resolve,reject)=>{pending={resolve,reject};firmware.stdin.write(command+'\n');});
}

// A deterministic host clock preserves timer registration order. A USB OUT
// write can complete before application setup is ready; its queued CR command
// is admitted after the measured production initialization plus an optional
// modeled inventory workload, then one loop tick. This is not a full boot model.
let now=0,nextId=0;
const jobs=new Map();
globalThis.setTimeout=(callback,delay=0)=>{
  const id=++nextId;jobs.set(id,{at:now+Number(delay),callback,id});return id;
};
globalThis.clearTimeout=id=>jobs.delete(id);
Date.now=()=>1791217040000+now;
let writes=0;
class Port{
  async open(options){
    assert.deepEqual(options,{baudRate:115200});
    this.readable=new ReadableStream({start(controller){output=controller;},cancel(){output=null;}});
    this.writable=new WritableStream({write:bytes=>{
      writes++;
      assert.equal(Buffer.from(bytes).toString(),'time 1791217040\r','Actual GUI first command must use CR only');
      setTimeout(()=>device('WRITE '+Buffer.from(bytes).toString('hex')),Math.max(readyMs+1-now,1));
    }});
  }
  async close(){
    assert(!this.readable.locked&&!this.writable.locked,'Stock cleanup must release the native locks');
    await device('CLOSE');
  }
  async setSignals(){assert.fail('No reset or explicit DTR may be added to satisfy bootstrap');}
}
const port=new Port();
Object.defineProperty(globalThis,'navigator',{configurable:true,
  value:{userAgent:'Linux Node host fixture',serial:{requestPort:async()=>port}}});
const {SerialCLI}=await import('data:text/javascript;base64,'+readFileSync(process.argv[2]).toString('base64'));
const cli=new SerialCLI(false);
assert.equal(cli.responseTimeout,5000,'Do not widen the stock GUI deadline');
const app={connecting:false,connected:false,locked:true};
const alerts=[];let dataReads=0;
const bootstrap=Function('cli','app','showMessage','getData','getPresets','alert',
  readFileSync(process.argv[3],'utf8')+'\nreturn {connect,disconnect};');
const gui=bootstrap(cli,app,()=>{},async()=>{dataReads++;},async()=>{},message=>alerts.push(message));
let finished=false;
if(preconnectIdleMs>0){
  // No host byte or SerialCLI operation precedes this idle interval. The
  // first complete command remains the untouched GUI's single time request.
  await device('TIME '+preconnectIdleMs);
  assert.equal(writes,0,'Preconnect idle gained artificial UART traffic');
}
const connection=gui.connect().finally(()=>{finished=true;});
try{
  for(let step=0;step<20&&!finished;step++){
    await turn();
    if(finished)break;
    const next=[...jobs.values()].sort((a,b)=>a.at-b.at||a.id-b.id)[0];
    assert(next,'Bootstrap stalled without a pending host deadline');
    jobs.delete(next.id);now=next.at;
    await next.callback();
    await turn();
  }
  await connection;
  assert.equal(writes,1,'Do not retry the first command to turn failure into PASS');
  assert.equal(app.connected,true,'initial time missed the stock 5000 ms deadline');
  assert.equal(app.locked,false);
  assert.equal(dataReads,1,'Configuration reads must follow successful initial time');
  assert.deepEqual(alerts,[]);
  assert(cli.reader&&cli.writer&&port.readable.locked&&port.writable.locked,
    'The actual GUI retains reader and writer throughout the connected session');
  await gui.disconnect();
  assert.equal(app.connected,false);
  assert.equal(app.locked,true);
  assert.equal(cli.port,null);
  console.log('Actual config GUI: stock 5000 ms time bootstrap, production startup timing, CR-only command and CRLF response passed');
}finally{
  if(cli.port)await cli.disconnect();
  firmware.stdin.end();
}
