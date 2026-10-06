// Only the SerialPort device boundary is simulated. The console, CRLF parser,
// encoder, streams, open/close and command writes come from the pinned website.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import {setTimeout as delay} from 'node:timers/promises';

const {SerialConsole} = await import('data:text/javascript;base64,' +
  readFileSync(process.argv[2]).toString('base64'));
const firmware = spawn(process.argv[3], [], {stdio:['pipe','pipe','inherit']});
const rawUart = process.argv[4] === '1';
let stream, pending, state;
let writes = 0;
createInterface({input:firmware.stdout}).on('line', line => {
  if (line.startsWith('DATA ')) {
    const bytes = Buffer.from(line.slice(5), 'hex');
    // Delimiters must work when CR and LF arrive in separate USB transfers.
    for (let n=0; n<bytes.length; n++) stream.enqueue(new Uint8Array(bytes.subarray(n,n+1)));
  } else if (line.startsWith('STATE ')) state=line.slice(6).split(' ').map(Number);
  else if (line==='DONE') {const done=pending;pending=null;done.resolve();}
});
firmware.on('exit', code => {if(pending) pending.reject(Error('Firmware exited: '+code));});
function command(text) {
  assert(!pending, 'Peripheral calls must be serialized');
  return new Promise((resolve,reject)=>{pending={resolve,reject};firmware.stdin.write(text+'\n');});
}
class Port {
  async open(options) {
    assert.deepEqual(options,{baudRate:115200});
    this.readable=new ReadableStream({start(controller){stream=controller;},cancel(){stream=null;}});
    this.writable=new WritableStream({write(bytes){++writes;return command('WRITE '+Buffer.from(bytes).toString('hex'));}});
  }
  async close(){await command('CLOSE');}
  async setSignals(){throw Error('The stock console must work without a reset or explicit DTR');}
}
let client, lines;
async function connect() {
  lines=[];client=new SerialConsole(new Port());client.onOutput=line=>lines.push(line);
  client.connect(); await delay(0); assert(client.connected);
}
async function query(text, expected, label) {
  const start=lines.length;
  await client.sendCommand(text);
  // All device work is synchronous at the pipe boundary, but Web Streams
  // delivery is asynchronous. Bound it rather than making a wall-time sleep.
  for(let n=0;n<50;n++) {
    if(lines.slice(start).join('').includes(expected)) return;
    await delay(2);
  }
  assert.fail(label+': stock console did not display the firmware reply');
}
try {
  await connect();
  await query('set powersaving on','  -> OK - powersaving on\n','power-saving setter');
  await query('get powersaving','  -> > on\n','power-saving getter');
  for(const elapsed of [121000,180001,360000,1800000,10800000,0xfffffffe,0,180001]) {
    const before=writes;
    await command('TIME '+elapsed);
    assert.equal(writes,before,'An idle web console gained an artificial keepalive');
    await query('get powersaving','  -> > on\n','idle query');
    assert.equal(state[1],0,'An open web console entered light sleep');
  }
  await client.disconnect();await connect();
  await query('get powersaving','  -> > on\n','reopen query');
  await query('set powersaving off','  -> OK - powersaving off\n','disable power saving');
  await command('HOST_OFF');await command('TIME 180002');
  assert.equal(state[1],0,'Disabled power saving slept');
  await query('set powersaving on','  -> OK - powersaving on\n','enable battery power saving');
  // Closing Web Serial or disconnecting the USB-to-UART bridge cannot prove
  // that a raw UART driver is no longer needed. Only driver disposal releases
  // its sleep veto; native CDC continues using actual host availability.
  if(rawUart) await command('DRIVER_END');
  // Expire native CDC's existing 120-second host-loss grace, measured from
  // the last positive host observation at 180001 after the clock wrapped.
  await command('TIME 300001');
  assert.equal(state[1],1,'USB protection permanently disabled battery power saving');
  console.log('Official console: CRLF, no-DTR idle, power saving, reopen and released-driver sleep passed');
} finally {
  if(client?.connected) await client.disconnect();
  firmware.stdin.end();
}
