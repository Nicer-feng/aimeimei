// 依据云市场 cmapi00072369 的公开响应契约构造，不含真实运单或凭证。
const http=require('http');
http.createServer((req,res)=>{
  const u=new URL(req.url,'http://localhost');
  if(u.pathname!=='/api/LogisticsDetail'){res.writeHead(501);res.end('Endpoint not modeled');return;}
  let arg;
  try{arg=JSON.parse(u.searchParams.get('logistics_interface')).arg0;}catch{res.writeHead(400);res.end('{}');return;}
  if(req.headers.authorization!=='APPCODE synthetic-test-code'||!arg.mailNo||!arg.cpCode||arg.appCode!=='aliyun_public'){
    res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({success:'false',errorCode:'400'}));return;
  }
  const raw={success:'true',errorCode:'0',result:{code:'0',data:JSON.stringify({lastState:'TRANSPORT',detail:[{opTime:'2026-10-22 12:00:00',opMessage:'测试包裹已揽收'},{opTime:'2026-10-22 13:00:00',opMessage:'测试包裹运输中'}]})}};
  res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(raw));
}).listen(process.env.PORT||4901);
