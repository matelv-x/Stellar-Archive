'use strict';

const http=require('http');
const fs=require('fs');
const os=require('os');
const path=require('path');
const {execFileSync}=require('child_process');
const {chromium}=require('/Users/marcinmagierski/Documents/Codex/2026-09-06/x20-cz/work/test-tools/node_modules/playwright');

const root=path.resolve(__dirname,'../payload/stellar-archive');
const output=process.argv[2]||path.join(__dirname,'stellar-archive-galaxy-animation-preview.mp4');
const frames=fs.mkdtempSync(path.join(os.tmpdir(),'stellar-archive-animation-'));
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.png':'image/png','.svg':'image/svg+xml'};

const server=http.createServer((request,response)=>{
  const requestPath=new URL(request.url,'http://127.0.0.1').pathname;
  if(requestPath==='/stargate/get/address_book'){
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({address_book:{standard:{type:'standard',gate_address:[27,7,15,32,12,30]}}}));
    return;
  }
  if(requestPath==='/stargate/get/dialing_status'){
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({gate_name:'Test Gate',local_address:[27,7,15,32,12,30]}));
    return;
  }
  const relative=requestPath==='/'?'index.html':requestPath.replace(/^\/stellar-archive\/?/,'').replace(/^\//,'');
  if(relative.startsWith('data/integration-nav.js')){
    response.writeHead(200,{'content-type':'text/javascript; charset=utf-8'});
    response.end('window.STELLAR_ARCHIVE_NAV={"mode":"retro","dialTarget":"retro","items":[{"label":"HOME","href":"/retro/dial.html"},{"label":"SYMBOLS","href":"/retro/symbol_overview.html"},{"label":"ADMIN","href":"/config.htm"}]};');
    return;
  }
  const file=path.resolve(root,relative||'index.html');
  if(!file.startsWith(`${root}${path.sep}`)&&file!==path.join(root,'index.html')){response.writeHead(403);response.end();return;}
  fs.readFile(file,(error,data)=>{if(error){response.writeHead(404);response.end();return}response.writeHead(200,{'content-type':mime[path.extname(file)]||'application/octet-stream'});response.end(data)});
});

(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1256,height:768}});
    await page.goto(`http://127.0.0.1:${server.address().port}/stellar-archive/?mode=retro`);
    await page.waitForSelector('.star-chart');
    const chart=await page.locator('.star-chart').boundingBox();
    if(!chart)throw new Error('Missing star chart');
    for(let frame=0;frame<64;frame++){
      await page.screenshot({path:path.join(frames,`frame-${String(frame).padStart(3,'0')}.png`),clip:chart});
      await page.waitForTimeout(125);
    }
    execFileSync('/opt/homebrew/bin/ffmpeg',['-y','-framerate','8','-i',path.join(frames,'frame-%03d.png'),'-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p','-crf','19','-movflags','+faststart',output],{stdio:'ignore'});
    process.stdout.write(`${output}\n`);
  }finally{
    await browser.close();
    await new Promise(resolve=>server.close(resolve));
    fs.rmSync(frames,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1});
