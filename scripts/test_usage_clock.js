const assert = require('node:assert/strict');
const UsageClock = require('../res/usage-clock.js');
const vm = require('node:vm');
const fs = require('node:fs');
for (const crypto of [undefined, { getRandomValues: require('node:crypto').webcrypto.getRandomValues.bind(require('node:crypto').webcrypto) }]) {
  const context = { crypto, module: { exports: {} } };
  vm.runInNewContext(fs.readFileSync(require.resolve('../res/usage-clock.js'), 'utf8'), context);
  const Clock = context.module.exports;
  const ids = new Set(Array.from({length:1000}, () => Clock.eventId()));
  assert.equal(ids.size, 1000);
  for (const id of ids) assert.match(id, /^[a-zA-Z0-9_-]{8,80}$/);
}
const sum = c => c.pending.reduce((n,p) => n+p.end_ms-p.start_ms,0);
const make = () => new UsageClock(1000000,0);
let c=make();
c.step(0,true,'work');c.step(5000,true,'work');assert.equal(sum(c),0);
c.step(5000,true,'work',true);c.step(10000,true,'work');assert.equal(sum(c),5000);
c.step(12000,false,'work');c.step(17000,false,'work');assert.equal(sum(c),7000);
c.step(17000,true,'work',true);c.step(20000,true,'reading');c.step(25000,true,'reading');
assert.equal(c.pending.filter(p=>p.mode==='reading').reduce((n,p)=>n+p.end_ms-p.start_ms,0),5000);
c=make();c.step(0,true,'work',true);
for(let t=5000;t<=140000;t+=5000)c.step(t,true,'work');
assert.equal(sum(c),120000);
c.step(141000,true,'work',true);c.step(146000,true,'work');assert.equal(sum(c),125000);
c=make();c.step(0,true,'work',true);c.step(5000,true,'work');c.step(305000,true,'work');c.step(310000,true,'work');assert.equal(sum(c),5000);
c.step(310000,true,'work',true);c.step(315000,true,'work');assert.equal(sum(c),10000);
assert.ok(c.pending.every(p=>p.end_ms-p.start_ms<=30000));
const batch=c.take(315000);assert.equal(batch.length,1);assert.equal(sum(c),0);
console.log('PASS no-input, focus, mode boundary, idle, resume, suspension, bounded reports, stale queue');
