// Run against file_share/tests/server.py only. IMM is stubbed; no real tokens or billing.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const base=process.env.CLOUD_TEST_URL;assert.match(base||'',/^http:\/\/127\.0\.0\.1:18765$/);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const errors=[];
 async function client(username,viewport={width:1440,height:960}){
  const c=await browser.newContext({viewport});
  const captcha=await(await c.request.get(base+'/api/captcha')).json();
  const answer=[...captcha.image_svg.matchAll(/<text[^>]*>(.*?)<\/text>/g)].map(x=>x[1]).join('');
  assert.equal((await c.request.post(base+'/api/login',{data:{username,password:'test-password',captcha_id:captcha.captcha_id,captcha:answer}})).status(),200);
  await c.route('https://g.alicdn.com/IMM/office-js/**',route=>route.fulfill({contentType:'application/javascript',body:`window.aliyun={config:({mount})=>{mount.textContent='模拟协同编辑器';return {setToken(){},ready:async()=>true,save:async()=>({result:'nochange'}),destroy(){mount.textContent=''},ApiEvent:{AddApiEventListener(){}}}}};`}));
  const p=await c.newPage();p.on('pageerror',e=>errors.push(String(e)));return {c,p};
 }
 async function api(c,path,data){const r=data===undefined?await c.request.get(base+path):await c.request.post(base+path,{data,headers:{'X-Share-Request':'1'}});assert.equal(r.status(),200,await r.text());return r.json();}
 try{
  const owner=await client('admin'),member=await client('member');
  await api(owner.c,'/api/file-share/admin/platform/access',{user_id:'member',enabled:true});
  // Minimal test bytes are accepted only by the mock OSS / fixture MIME check.
  const content=Buffer.from('PK\x03\x04ui-collaboration');const crypto=require('node:crypto');
  const f=await api(owner.c,'/api/file-share/admin/uploads',{filename:'UI协作文档.docx',size:content.length,mime_type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',sha256:crypto.createHash('sha256').update(content).digest('hex')});
  const part=await api(owner.c,`/api/file-share/admin/uploads/${f.id}/part`,{part_number:1,content_md5:crypto.createHash('md5').update(content).digest('base64')});
  const put=await owner.c.request.put(part.url,{data:content,headers:part.headers});assert.equal(put.status(),200);
  await api(owner.c,`/api/file-share/admin/uploads/${f.id}/complete`,{parts:[{part_number:1,etag:put.headers().etag}]});
  await owner.p.goto(base+'/admin/share');await owner.p.waitForSelector('[data-section="files"].active');
  await owner.p.locator(`[data-menu="${f.id}"]`).click();await owner.p.getByRole('button',{name:'管理协作',exact:true}).click();
  await owner.p.locator('#officeMemberUsername').fill('member');await owner.p.getByRole('button',{name:'邀请共同编辑',exact:true}).click();
  await owner.p.waitForFunction(()=>document.querySelector('#dialogBody')?.textContent.includes('member')||document.querySelector('#dialog')?.textContent.includes('member'));
  await owner.p.evaluate(()=>FS.close());await owner.p.waitForTimeout(250);
  await member.p.goto(base+'/admin/share#collaboration');await member.p.getByRole('button',{name:'共同编辑',exact:true}).click();
  await member.p.waitForSelector('#officeMount:has-text("模拟协同编辑器")');
  await owner.p.locator(`[data-menu="${f.id}"]`).click();await owner.p.getByRole('button',{name:'在线编辑',exact:true}).click();
  await owner.p.waitForSelector('#officeMount:has-text("模拟协同编辑器")');
  await owner.p.waitForFunction(()=>document.getElementById('officeParticipants').textContent.includes('member'));
  await member.p.locator('#officeSaveVersion').click();await member.p.waitForFunction(()=>/已保存版本|内容无变化/.test(document.getElementById('officeStatus').textContent));
  await member.p.locator('#officeShowVersions').click();await member.p.waitForSelector('#officeVersionsBody .office-version-row');
  assert.equal(await member.p.locator('#officeVersionsBody [data-publish]').count(),0);
  await member.p.locator('#officeVersionsClose').click();
  await owner.p.locator('#officeClose').click();await owner.p.locator('#officeCloseDraft').click();await owner.p.waitForFunction(()=>!document.getElementById('officeEditor').open);
  assert.equal(await member.p.locator('#officeEditor').evaluate(e=>e.open),true);
  await member.p.setViewportSize({width:390,height:844});await member.p.waitForTimeout(200);
  assert(await member.p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await member.p.screenshot({path:'/private/tmp/cloud-collaboration-mobile.png',fullPage:true});
  await member.p.locator('#officeClose').click();await member.p.locator('#officeCloseDraft').click();await member.p.waitForFunction(()=>!document.getElementById('officeEditor').open);
  await owner.p.locator(`[data-menu="${f.id}"]`).click();await owner.p.getByRole('button',{name:'管理协作',exact:true}).click();
  await owner.p.locator('[data-remove-member]').click();await owner.p.locator('[data-remove-member]').click();
  await owner.p.waitForSelector('#dialog:has-text("尚未邀请协作者")');
  await member.p.setViewportSize({width:1440,height:960});await member.p.getByRole('button',{name:'刷新协作文档'}).click();
  await member.p.waitForSelector('#content:has-text("暂无协作文档")');
  await owner.p.screenshot({path:'/private/tmp/cloud-collaboration-desktop.png',fullPage:true});
  assert.deepEqual(errors,[]);console.log('PASS browser: owner invites existing account, separate-user join, participant names, save without publishing, owner-only publication UI, independent leave, mobile sizing, remove member and shared-list refresh; no JS errors');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
