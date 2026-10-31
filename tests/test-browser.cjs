'use strict';

const http=require('http');
const fs=require('fs');
const path=require('path');
const assert=require('assert');
const {chromium}=require('/Users/marcinmagierski/Documents/Codex/2026-09-06/x20-cz/work/test-tools/node_modules/playwright');

const root=path.resolve(__dirname,'../payload/stellar-archive');
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.png':'image/png','.svg':'image/svg+xml'};
let addonTask={state:'idle',message:'Ready'};
let addonPolls=0;
let aquilaInstalled=false;
let addonAction='install';
let restartRequests=0;
let statusRevision=0;
let staticImageRequests=[];
const systemActionRequests={restart:0,reboot:0,shutdown:0};

const server=http.createServer((request,response)=>{
  const requestPath=new URL(request.url,'http://127.0.0.1').pathname;
  if(requestPath==='/stargate/get/address_book'){
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({status_freshness:{stale:false},address_book:{
      standard:{type:'standard',gate_address:[27,7,15,32,12,30]},
      local:{type:'fan',gate_address:[7,5,20,27,32,21],is_gate_online:0},
      remote:{type:'fan',gate_address:[21,12,19,3,23,33],is_gate_online:statusRevision},
      lan:{type:'lan',gate_address:[3,7,11,19,22,30,34,36],is_gate_online:1},
      highlander:{type:'lan',gate_address:[14,3,4,22,38,35],is_gate_online:1},
      solarTalon:{type:'fan',gate_address:[21,5,29,10,14,34],is_gate_online:1}
    }}));
    return;
  }
  if(requestPath==='/stargate/get/dialing_status'){
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({gate_name:'Test Gate',local_address:[7,5,20,27,32,21]}));
    return;
  }
  if(requestPath==='/stargate/get/stellar_archive_update'){
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({success:true,current_version:'1.5.21',latest_version:'1.5.21',update_available:false}));
    return;
  }
  if(requestPath==='/stargate/get/stellar_archive_addons'){
    if(addonTask.state==='running'){
      addonPolls+=1;
      const stages=[
        {phase:'download',progress:20,message:'Downloading repository'},
        {phase:'verify',progress:50,message:'Verifying maintenance contract'},
        {phase:'install',progress:75,message:`Running verified ${addonAction} procedure`},
        {state:'complete',phase:'complete',progress:100,message:`Aquila Symbol Patch ${addonAction} complete`}
      ];
      addonTask={state:'running',...stages[Math.min(addonPolls-1,stages.length-1)]};
      if(addonTask.state==='complete')aquilaInstalled=addonAction!=='uninstall';
    }
    const aquila={id:'aquila-symbol-patch',name:'Aquila Symbol Patch',repository:'matelv-x/Aquila-Symbol-Patch',repository_url:'https://github.com/matelv-x/Aquila-Symbol-Patch',installed:aquilaInstalled,current_revision:aquilaInstalled?'222222222222':null,latest_revision:'222222222222',update_available:false,check_error:'',can_install:!aquilaInstalled,can_update:aquilaInstalled,can_uninstall:aquilaInstalled,restart_required:true,task:addonTask};
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({success:true,addons:[{id:'alarm-clock',name:'Alarm Clock',repository:'matelv-x/Alarm-Clock',repository_url:'https://github.com/matelv-x/Alarm-Clock',installed:true,current_revision:'111111111111',latest_revision:'111111111111',update_available:false,check_error:'',can_install:false,can_update:true,can_uninstall:true,task:{state:'idle',message:'Ready'}},...(aquilaInstalled?[aquila]:[])],available:aquilaInstalled?[]:[aquila]}));
    return;
  }
  if(/^\/stargate\/do\/stellar_archive_addon_(install|uninstall)$/.test(requestPath)&&request.method==='POST'){
    addonAction=requestPath.endsWith('_uninstall')?'uninstall':'install';
    addonPolls=0;
    addonTask={state:'running',phase:'prepare',progress:5,message:`Preparing Aquila Symbol Patch ${addonAction}`};
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({success:true,message:`${addonAction} started`,task:addonTask}));
    return;
  }
  if(requestPath==='/stargate/do/stellar_archive_restart'&&request.method==='POST'){
    restartRequests+=1;
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({success:true,message:'Restart scheduled',service:'stargate-test.service'}));
    return;
  }
  const systemAction=requestPath.match(/^\/stargate\/do\/(restart|reboot|shutdown)$/);
  if(systemAction&&request.method==='POST'){
    systemActionRequests[systemAction[1]]+=1;
    response.writeHead(200,{'content-type':'application/json'});
    response.end(JSON.stringify({success:true}));
    return;
  }
  const relative=requestPath==='/'?'index.html':requestPath.replace(/^\/stellar-archive\/?/,'').replace(/^\//,'');
  if(/^assets\/.*\.(?:png|webp)$/.test(relative))staticImageRequests.push(relative);
  if(relative.startsWith('data/integration-nav.js')){
    const items=[
      {label:'HOME',href:'/retro/dial.html'},
      {label:'SYMBOLS',href:'/retro/symbol_overview.html'},
      {label:'ADMIN',children:[{label:'CONFIGURATION',href:'/config.htm'},{label:'RESTART SOFTWARE',action:'restart'},{label:'REBOOT',action:'reboot'},{label:'SHUTDOWN',action:'shutdown'}]},
      {label:'ALARM CLOCK',href:'/alarm_clock.htm',addon:true},
      ...(aquilaInstalled?[{label:'AQUILA SYMBOL',href:'/aquila.htm',addon:true}]:[]),
      {label:'HELP',href:'/help.htm'}
    ];
    response.writeHead(200,{'content-type':'text/javascript; charset=utf-8'});
    response.end(`window.STELLAR_ARCHIVE_NAV=${JSON.stringify({mode:'retro',dialTarget:'retro',homeByHost:{'127.0.0.1':'/receiver.html','archive.example.test':'/'},items})};`);
    return;
  }
  const file=path.resolve(root,relative||'index.html');
  if(!file.startsWith(`${root}${path.sep}`)&&file!==path.join(root,'index.html')){
    response.writeHead(403); response.end(); return;
  }
  fs.readFile(file,(error,data)=>{
    if(error){response.writeHead(404);response.end();return;}
    response.writeHead(200,{'content-type':mime[path.extname(file)]||'application/octet-stream','cache-control':'no-store'});
    response.end(data);
  });
});

(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port;
  const browser=await chromium.launch({headless:true,args:['--host-resolver-rules=MAP archive.example.test 127.0.0.1']});
  const page=await browser.newPage({viewport:{width:1728,height:900}});
  try{
    await page.goto(`http://127.0.0.1:${port}/stellar-archive/?mode=original`);
    await page.waitForSelector('#select-address');
    await page.waitForTimeout(500);
    assert.deepStrictEqual(await page.locator('#category option').allTextContents(),['ALL 131 RECORDS','STANDARD · 35','FAN · 94','LAN · 2']);
    const spriteThumbnails=await page.locator('#worlds .mini-planet > .mini-planet-image').count();
    const archiveImageData=await page.evaluate(()=>({
      assetCount:window.STELLAR_ARCHIVE_DATA.worlds.filter(world=>world.visualAsset).length,
      assets:window.STELLAR_ARCHIVE_DATA.worlds.map(world=>world.visualAsset).filter(Boolean)
    }));
    assert.strictEqual(spriteThumbnails,archiveImageData.assetCount);
    const visualAssets=new Set(archiveImageData.assets.map(asset=>`assets/${asset}`));
    const initialVisualRequests=staticImageRequests.filter(asset=>visualAssets.has(asset));
    assert(initialVisualRequests.length<=2,`catalogue loaded more than the selected full-size planet artwork: ${initialVisualRequests.length} requests`);
    const requestCounts=initialVisualRequests.reduce((counts,asset)=>counts.set(asset,(counts.get(asset)||0)+1),new Map());
    assert(Math.max(0,...requestCounts.values())<=2,'the same planet asset was downloaded more than twice');
    const spriteRequests=staticImageRequests.filter(asset=>/^assets\/optimized\/[a-f0-9]{64}\.webp$/.test(asset));
    assert.strictEqual(spriteRequests.length,1,'the content-addressed catalogue sprite must be downloaded exactly once');
    await page.evaluate(()=>{const list=document.querySelector('#worlds');for(const ratio of [.95,.15,.75,.35,1])list.scrollTop=(list.scrollHeight-list.clientHeight)*ratio});
    const rapidScrollThumbnails=await page.evaluate(()=>{
      const list=document.querySelector('#worlds');
      const bounds=list.getBoundingClientRect();
      return [...list.querySelectorAll('.world')].filter(row=>{const rect=row.getBoundingClientRect();return rect.bottom>bounds.top&&rect.top<bounds.bottom}).map(row=>getComputedStyle(row.querySelector('.mini-planet-image')).backgroundImage);
    });
    assert(rapidScrollThumbnails.length>0&&rapidScrollThumbnails.every(image=>image.includes('/assets/optimized/')),'rapid full-screen scrolling must keep every visible planet thumbnail assigned');
    await page.evaluate(()=>{document.querySelector('#worlds').scrollTop=0});
    assert.strictEqual(new Set(archiveImageData.assets).size,131,'each archive record must have its own visual asset');
    assert.deepStrictEqual(await page.evaluate(()=>{
      const approved={
        'standard-001-abydos':'archive-approved-standard-001-abydos-v2.png',
        'standard-005-chulak':'archive-approved-standard-005-chulak-v2.png',
        'standard-008-destroyers':'archive-approved-standard-008-destroyers-v3.png',
        'standard-010-edora':'archive-approved-standard-010-edora-v2.png',
        'standard-035-destiny':'archive-approved-standard-035-destiny-v4.png',
        'lan-001-seed-ship-1':'archive-approved-lan-001-seed-ship-1-v2.png'
      };
      return window.STELLAR_ARCHIVE_DATA.worlds.filter(world=>world.visualAsset!==(approved[world.id]||`archive-concept-${world.id}-v1.png`)).map(world=>world.id);
    }),[],'one or more records did not receive its mapped concept image');
    const artworkPresentation=await page.evaluate(()=>{
      const thumbnail=document.querySelector('[data-id="standard-001-abydos"] .mini-planet');
      const image=thumbnail.querySelector('.mini-planet-image');
      const profile=document.querySelector('#planet');
      return {
        thumbnailRadius:getComputedStyle(thumbnail).borderRadius,
        imageFilter:getComputedStyle(image).filter,
        profileRadius:getComputedStyle(profile).borderRadius,
        profileFilter:getComputedStyle(profile).filter,
        profileImage:getComputedStyle(profile).backgroundImage,
        ringImage:getComputedStyle(thumbnail,'::before').backgroundImage,
        raysImage:getComputedStyle(thumbnail,'::after').backgroundImage
      };
    });
    assert.strictEqual(artworkPresentation.thumbnailRadius,'50%');
    assert.strictEqual(artworkPresentation.imageFilter,'none');
    assert.strictEqual(artworkPresentation.profileRadius,'18px');
    assert.strictEqual(artworkPresentation.profileFilter,'none');
    assert(artworkPresentation.profileImage.includes('archive-approved-standard-001-abydos-v2.png'));
    assert(artworkPresentation.ringImage.includes('radial-gradient'));
    assert.strictEqual(artworkPresentation.raysImage,'none');
    assert.strictEqual(await page.locator('[data-id="standard-001-abydos"] .mini-planet').evaluate(node=>node.classList.contains('status-standard')),true);
    assert.strictEqual(await page.locator('[data-id="fan-001-kristian-tysse"] .mini-planet').evaluate(node=>node.classList.contains('status-online')),true);
    assert.strictEqual(await page.locator('[data-id="fan-002-tesseract"] .mini-planet').evaluate(node=>node.classList.contains('status-offline')),true);
    assert.strictEqual(await page.locator('[data-id="lan-001-seed-ship-1"] .mini-planet').evaluate(node=>node.classList.contains('status-lan')),true);
    assert.strictEqual(await page.locator('[data-id="fan-071-highlander"] .mini-planet').evaluate(node=>node.classList.contains('status-lan')),true);
    assert.strictEqual(await page.locator('[data-id="fan-094-solar-talon"] .mini-planet').evaluate(node=>node.classList.contains('status-online')),true);
    assert.strictEqual(await page.locator('[data-id="fan-095-solar-talon-belgium-gate"] .mini-planet').evaluate(node=>node.classList.contains('status-online')),true);
    await page.evaluate(()=>{window.__firstArchiveWorld=document.querySelector('#worlds .world')});
    statusRevision=1;
    await page.evaluate(()=>refreshGateStatuses());
    assert.strictEqual(await page.evaluate(()=>window.__firstArchiveWorld===document.querySelector('#worlds .world')),true,'status refresh rebuilt the catalogue list');
    assert.strictEqual(await page.locator('[data-id="fan-002-tesseract"] .mini-planet').evaluate(node=>node.classList.contains('status-online')),true,'live refresh did not update the thumbnail glow');
    const original=await page.evaluate(()=>({
      address:window.STELLAR_ARCHIVE_DATA.worlds[0].storedAddress.join('-'),
      href:document.querySelector('#select-address').getAttribute('href'),
      home:document.querySelector('.brand').getAttribute('href'),
      homeButton:[...document.querySelectorAll('#integration-nav a')].find(link=>link.textContent.trim()==='HOME')?.getAttribute('href')
    }));
    assert.strictEqual(original.href,`/receiver.html?address=${original.address}&source=stellar-archive`);
    assert.strictEqual(original.home,'/receiver.html');
    assert.strictEqual(original.homeButton,'/receiver.html');
    assert.strictEqual(await page.locator('#sort-order').inputValue(),'registered');
    assert.deepStrictEqual(
      await page.locator('#worlds .world').evaluateAll(nodes=>nodes.slice(0,6).map(node=>node.dataset.id)),
      await page.evaluate(()=>window.STELLAR_ARCHIVE_DATA.worlds.slice(0,6).map(world=>world.id))
    );
    await page.selectOption('#sort-order','alphabetical');
    const alphabeticalNames=await page.locator('#worlds .world-name').allTextContents();
    assert.deepStrictEqual(alphabeticalNames,[...alphabeticalNames].sort((a,b)=>a.localeCompare(b,undefined,{sensitivity:'base',numeric:true})));
    await page.screenshot({path:path.join(__dirname,'validation-catalogue-sort.png'),fullPage:false});
    await page.selectOption('#category','fan');
    assert.strictEqual(
      await page.locator('#worlds .world-name').first().textContent(),
      await page.evaluate(()=>window.STELLAR_ARCHIVE_DATA.worlds.filter(world=>world.category==='fan').map(world=>world.name).sort((a,b)=>a.localeCompare(b,undefined,{sensitivity:'base',numeric:true}))[0])
    );
    await page.selectOption('#sort-order','registered');
    assert.strictEqual(
      await page.locator('#worlds .world').first().getAttribute('data-id'),
      await page.evaluate(()=>window.STELLAR_ARCHIVE_DATA.worlds.find(world=>world.category==='fan').id)
    );
    await page.selectOption('#category','all');
    assert.deepStrictEqual(await page.evaluate(()=>({
      freshStandard:gateOnline({type:'standard',gate_address:[9]},'',true),
      staleStandard:gateOnline({type:'standard',gate_address:[9]},'',false),
      freshFan:gateOnline({type:'fan',gate_address:[8],is_gate_online:1},'',true),
      staleFan:gateOnline({type:'fan',gate_address:[8],is_gate_online:1},'',false),
      staleLan:gateOnline({type:'lan',gate_address:[7],is_gate_online:1},'',false),
      local:gateOnline({type:'fan',gate_address:[1,2,3]},'1-2-3',false)
    })),{
      freshStandard:true,
      staleStandard:false,
      freshFan:true,
      staleFan:false,
      staleLan:true,
      local:true
    });

    await page.goto(`http://127.0.0.1:${port}/stellar-archive/?mode=retro`);
    await page.waitForSelector('#select-address');
    await page.waitForFunction(()=>document.querySelector('#installed-gate-name').textContent==='TEST GATE');
    const six=await page.evaluate(()=>({
      address:window.STELLAR_ARCHIVE_DATA.worlds[0].storedAddress.join('-'),
      length:window.STELLAR_ARCHIVE_DATA.worlds[0].storedAddress.length,
      href:document.querySelector('#select-address').getAttribute('href'),
      home:document.querySelector('.brand').getAttribute('href'),
      homeButton:[...document.querySelectorAll('#integration-nav a')].find(link=>link.textContent.trim()==='HOME')?.getAttribute('href')
    }));
    assert.strictEqual(six.length,6);
    assert.strictEqual(six.href,`/receiver.html?address=${six.address}&source=stellar-archive`);
    assert.strictEqual(six.home,'/receiver.html');
    assert.strictEqual(six.homeButton,'/receiver.html');

    await page.goto(`http://archive.example.test:${port}/stellar-archive/?mode=retro`);
    await page.waitForSelector('#select-address');
    const ll=await page.evaluate(()=>({
      address:window.STELLAR_ARCHIVE_DATA.worlds[0].storedAddress.join('-'),
      href:document.querySelector('#select-address').getAttribute('href'),
      home:document.querySelector('.brand').getAttribute('href'),
      homeButton:[...document.querySelectorAll('#integration-nav a')].find(link=>link.textContent.trim()==='HOME')?.getAttribute('href')
    }));
    assert.strictEqual(ll.href,`/?address=${ll.address}&source=stellar-archive`);
    assert.strictEqual(ll.home,'/');
    assert.strictEqual(ll.homeButton,'/');

    await page.goto(`http://127.0.0.1:${port}/stellar-archive/?mode=retro`);
    await page.waitForSelector('#select-address');
    assert.strictEqual(await page.locator('#installed-gate-name').textContent(),'TEST GATE');
    assert.strictEqual(await page.locator('.gaia-motion > .gaia-layer').count(),3);
    assert.strictEqual(await page.locator('.gaia-core').evaluate(element=>getComputedStyle(element).animationDuration),'75s');
    assert.strictEqual(await page.locator('.gaia-middle').evaluate(element=>getComputedStyle(element).animationDuration),'135s');
    assert.strictEqual(await page.locator('.gaia-outer').evaluate(element=>getComputedStyle(element).animationDuration),'240s');
    assert.strictEqual(await page.evaluate(()=>new Promise(resolve=>{const image=new Image();image.onload=()=>resolve(image.naturalWidth);image.onerror=()=>resolve(0);image.src='assets/gaia-milky-way-2025-face-on.jpg'})),1600);
    const motionStart=await page.locator('#connections .network-link').first().getAttribute('x2');
    await page.waitForTimeout(500);
    const motionEnd=await page.locator('#connections .network-link').first().getAttribute('x2');
    assert.notStrictEqual(motionEnd,motionStart,'Gaia-inspired address points must move at runtime');
    assert(Number(await page.locator('#nodes .node').first().getAttribute('data-orbit-duration'))>=75);
    const orbitDurations=(await page.locator('#nodes .node').evaluateAll(nodes=>nodes.map(node=>Number(node.dataset.orbitDuration))));
    assert(Math.max(...orbitDurations)-Math.min(...orbitDurations)>20,'node orbital periods must differ by galactic radius');
    assert.strictEqual(await page.locator('.footnote').count(),0);
    assert.deepStrictEqual(await page.locator('#integration-nav > .integration-button, #integration-nav > .integration-dropdown > summary').allTextContents(),[
      'HOME','SYMBOLS','ADMIN','ALARM CLOCK','HELP','ABOUT'
    ]);
    await page.locator('.integration-dropdown summary').click();
    await page.waitForSelector('.integration-dropdown[open] .integration-menu');
    assert.deepStrictEqual(await page.locator('.integration-menu .integration-button').allTextContents(),['CONFIGURATION','RESTART SOFTWARE','REBOOT','SHUTDOWN']);
    await page.getByRole('button',{name:'RESTART SOFTWARE'}).click();
    await page.waitForSelector('#system-action-confirm[open]');
    assert.strictEqual(await page.locator('#system-action-title').textContent(),'RESTART SOFTWARE');
    assert.strictEqual(restartRequests,0,'system action must wait for in-page confirmation');
    const restartResponse=page.waitForResponse(response=>response.url().endsWith('/stargate/do/stellar_archive_restart'));
    await page.locator('#system-action-approve').click();
    await restartResponse;
    await page.waitForFunction(()=>document.querySelector('#system-action-confirm').open===false);
    assert.strictEqual(restartRequests,1,'confirmed restart must call the delayed maintenance endpoint once');
    await page.getByRole('button',{name:'REBOOT'}).click();
    assert.strictEqual(await page.locator('#system-action-title').textContent(),'REBOOT RASPBERRY PI');
    await page.locator('#system-action-cancel').click();
    assert.strictEqual(systemActionRequests.reboot,0,'cancelled reboot must not call its endpoint');
    await page.getByRole('button',{name:'SHUTDOWN'}).click();
    assert.strictEqual(await page.locator('#system-action-title').textContent(),'SHUT DOWN RASPBERRY PI');
    await page.locator('#system-action-cancel').click();
    assert.strictEqual(systemActionRequests.shutdown,0,'cancelled shutdown must not call its endpoint');
    await page.locator('.integration-dropdown summary').click();
    await page.getByRole('button',{name:'ABOUT'}).click();
    await page.waitForSelector('#dialog-links:not([hidden])');
    assert.strictEqual(await page.locator('#details > .eyebrow').textContent(),'ANCIENT STELLAR ARCHIVE · INSTALLED VERSION 1.5.21');
    assert.strictEqual(await page.locator('.addon-manager-heading h3').textContent(),'MATELV-X SOFTWARE MAINTENANCE');
    const maintenanceLabels=(await page.locator('.maintenance-fold > summary').allTextContents()).map(value=>value.trim());
    assert(maintenanceLabels[0].startsWith('INSTALLED MATELV-X SOFTWARE'));
    assert(maintenanceLabels[1].startsWith('AVAILABLE MATELV-X ADD-ONS'));
    assert((await page.locator('#dialog-links a').count())>=20);
    assert.strictEqual(await page.locator('#dialog-links a[href="https://www.gateworld.net/"]').count(),1);
    assert.strictEqual(await page.locator('#dialog-links a[href="https://www.cosmos.esa.int/web/gaia/milky-way"]').count(),1);
    assert((await page.locator('#dialog-copy').textContent()).includes('ESA/Gaia/DPAC'));
    assert.strictEqual(await page.locator('#dialog-maintenance:not([hidden])').count(),1);
    await page.waitForSelector('#addon-list .addon-row');
    assert.strictEqual(await page.locator('.maintenance-fold').count(),2);
    assert.strictEqual(await page.locator('#addon-list .addon-row').count(),1);
    assert.strictEqual(await page.locator('#available-addon-list .addon-row').count(),1);
    await page.locator('.maintenance-fold').nth(1).locator('summary').click();
    const installButton=page.locator('#available-addon-list button[data-addon-action="install"]');
    assert.strictEqual(await installButton.isDisabled(),true,'INSTALL must remain locked before repository information is opened');
    await page.evaluate(()=>{window.open=()=>({opener:null})});
    await page.locator('#available-addon-list button[data-addon-action="info"]').click();
    assert.strictEqual(await installButton.isDisabled(),false,'repository information must unlock INSTALL');
    await installButton.click();
    await page.waitForSelector('#addon-progress-overlay[data-state="confirm"]:not([hidden])');
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'CONFIRM INSTALL');
    assert.strictEqual(await page.locator('#addon-progress-name').textContent(),'Aquila Symbol Patch');
    assert.strictEqual(await page.locator('#addon-progress-close').textContent(),'CANCEL');
    assert.strictEqual(await page.locator('#addon-progress-restart').textContent(),'INSTALL');
    await page.locator('#addon-progress-restart').click();
    await page.waitForSelector('#addon-progress-overlay[data-state="running"]');
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'INSTALL IN PROGRESS');
    await page.waitForSelector('#addon-progress-restart:not([hidden])',{timeout:10000});
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'INSTALL COMPLETE');
    assert((await page.locator('#integration-nav').textContent()).includes('AQUILA SYMBOL'),'install must refresh and add its navigation button');
    assert.strictEqual(await page.locator('#addon-progress-close').textContent(),'LATER');
    assert.strictEqual(await page.locator('#addon-progress-bar').evaluate(element=>element.style.width),'100%');
    assert.strictEqual(await page.locator('.addon-progress-steps li.done').count(),3);
    assert.strictEqual(await page.locator('.addon-progress-steps li.active').textContent(),'COMPLETE');
    await page.screenshot({path:path.join(__dirname,'validation-addon-progress.png'),fullPage:false});
    await page.locator('#addon-progress-close').click();
    await page.waitForSelector('#addon-progress-overlay',{state:'hidden'});
    const aquilaRow=page.locator('#addon-list .addon-row').filter({hasText:'Aquila Symbol Patch'});
    await aquilaRow.locator('button[data-addon-action="uninstall"]').click();
    await page.waitForSelector('#addon-progress-overlay[data-state="confirm"]:not([hidden])');
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'CONFIRM UNINSTALL');
    assert.strictEqual(await page.locator('#addon-progress-name').textContent(),'Aquila Symbol Patch');
    assert.strictEqual(await page.locator('#addon-progress-close').textContent(),'CANCEL');
    assert.strictEqual(await page.locator('#addon-progress-restart').textContent(),'UNINSTALL');
    await page.screenshot({path:path.join(__dirname,'validation-addon-uninstall-confirm.png'),fullPage:false});
    await page.locator('#addon-progress-restart').click();
    await page.waitForSelector('#addon-progress-overlay[data-state="running"]');
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'UNINSTALL IN PROGRESS');
    await page.waitForSelector('#addon-progress-restart:not([hidden])',{timeout:10000});
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'UNINSTALL COMPLETE');
    assert(!(await page.locator('#integration-nav').textContent()).includes('AQUILA SYMBOL'),'uninstall must refresh and remove its navigation button');
    assert.strictEqual(await page.locator('.addon-progress-steps li').nth(2).textContent(),'REMOVE');
    const restartRequestsBeforeAddonRestart=restartRequests;
    await page.locator('#addon-progress-restart').click();
    await page.waitForSelector('#addon-progress-overlay[data-state="confirm-restart"]');
    assert.strictEqual(restartRequests,restartRequestsBeforeAddonRestart,'first restart click must only show the in-page confirmation');
    assert.strictEqual(await page.locator('#addon-progress-title').textContent(),'CONFIRM RESTART');
    assert.strictEqual(await page.locator('#addon-progress-close').textContent(),'CANCEL');
    assert.strictEqual(await page.locator('#addon-progress-restart').textContent(),'RESTART NOW');
    await page.locator('#addon-progress-restart').click();
    await page.waitForSelector('#addon-progress-overlay[data-state="restarting"]');
    await page.waitForFunction(()=>document.querySelector('#addon-progress-title').textContent==='SERVICE ONLINE');
    assert.strictEqual(restartRequests,restartRequestsBeforeAddonRestart+1,'confirmed restart must send exactly one request');
    await page.locator('#addon-progress-close').click();
    await page.waitForSelector('#addon-progress-overlay',{state:'hidden'});
    assert.strictEqual(await page.locator('#check-archive-update').count(),1);
    assert.strictEqual(await page.locator('#uninstall-archive').count(),1);
    await page.screenshot({path:path.join(__dirname,'validation-about-addons.png'),fullPage:false});
    await page.locator('#close-dialog').click();
    await page.setViewportSize({width:1256,height:768});
    await page.addStyleTag({content:'.planet{animation:none!important}'});
    await page.waitForFunction(()=>Math.abs(Number(document.querySelector('#archive-shell').dataset.scale)-(1256/1400))<.002);
    assert(Math.abs(Number(await page.locator('#archive-shell').getAttribute('data-scale'))-(1256/1400))<.002,'complete interface must share one compact-window scale factor');
    await page.locator('.integration-dropdown summary').click();
    await page.waitForSelector('.integration-dropdown[open] .integration-menu');
    const adminMenuAbovePage=await page.evaluate(()=>{
      const button=document.querySelector('.integration-menu .integration-button:last-child');
      const rect=button.getBoundingClientRect();
      const top=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
      return Boolean(top?.closest('.integration-menu'));
    });
    assert(adminMenuAbovePage,'Admin dropdown must remain above the destination and galaxy panels');
    await page.locator('.integration-dropdown summary').click();
    const layout=await page.evaluate(()=>{
      const box=selector=>document.querySelector(selector).getBoundingClientRect().toJSON();
      const worlds=document.querySelector('#worlds');
      const summary=[...document.querySelectorAll('.gate-summary p>span')].map(item=>item.getBoundingClientRect().toJSON());
      const glyphBoxes=[...document.querySelectorAll('.glyph-box')].map(item=>item.getBoundingClientRect().toJSON());
      const catalogue=document.querySelector('.catalogue');
      return {brand:box('.brand'),brandMark:document.querySelector('.brand-mark').getAttribute('src'),nav:box('#integration-nav'),gateName:box('.installed-gate'),gateNameText:document.querySelector('.installed-gate').textContent.trim(),catalogue:box('.catalogue'),catalogueScrollable:catalogue.scrollHeight>catalogue.clientHeight,catalogueOverflow:getComputedStyle(catalogue).overflowY,chart:box('.star-chart'),destination:box('.destination'),planetScene:box('.planet-scene'),planet:box('#planet'),console:box('.address-console'),consoleTitle:box('.console-title'),glyphArea:box('.glyph-area'),glyphBoxes,seal:box('.seal'),sealMark:document.querySelector('.seal>img').getAttribute('src'),selection:box('.selection'),viewport:box('#archive-viewport'),summary,worldsOverflowAmount:worlds.scrollHeight-worlds.clientHeight,worldsOverflow:getComputedStyle(worlds).overflowY,scrollMode:document.querySelector('#archive-shell').dataset.scrollMode,shortLayout:document.documentElement.classList.contains('short-window-layout'),bodyScroll:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}};
    });
    assert(layout.brand.right<=layout.nav.left+1,'scaled masthead brand must not overlap right-side navigation');
    assert(layout.gateName.bottom<=layout.nav.top+1,'installed gate name must appear above navigation buttons');
    assert(layout.catalogue.right<=layout.chart.left+1&&layout.chart.right<=layout.destination.left+1,'three primary panels must remain in one row');
    assert(layout.planet.left>=layout.planetScene.left-1&&layout.planet.right<=layout.planetScene.right+1&&layout.planet.top>=layout.planetScene.top-1&&layout.planet.bottom<=layout.planetScene.bottom+1,`planet image must shrink fully inside its scene: ${JSON.stringify({planet:layout.planet,scene:layout.planetScene})}`);
    assert(layout.summary.every((row,index)=>index===0||row.top>=layout.summary[index-1].bottom-1),'each gate-status colour must occupy its own line');
    assert.strictEqual(layout.brandMark,'assets/sgc-emblem-stellar-v1.png');
    assert.strictEqual(layout.sealMark,'assets/sgc-emblem-stellar-v1.png');
    assert.strictEqual(layout.gateNameText,'TEST GATE');
    assert(layout.consoleTitle.top>=layout.console.top&&layout.consoleTitle.bottom<=layout.console.bottom,'lower-frame heading must not be clipped');
    assert(layout.viewport.width<=1256+1,'scaled archive must fit the window width');
    assert(layout.shortLayout&&layout.scrollMode==='catalogue-panel','short desktop windows must scroll the complete catalogue panel');
    assert(layout.catalogueScrollable&&layout.catalogueOverflow==='auto','the left panel must provide one scrollbar like the destination panel');
    assert.strictEqual(layout.worldsOverflow,'visible','planet list must not trap scrolling inside its own viewport');
    assert(layout.worldsOverflowAmount<=40,'planet list must expand to its complete height apart from the decorative status corona');
    assert(layout.bodyScroll.width<=1256+1&&layout.bodyScroll.height<=768+1,'application must remain bounded by the small window');
    assert.strictEqual(await page.locator('#worlds .mini-planet > .mini-planet-image').count(),131,'short-window layout must retain every sprite thumbnail');
    await page.locator('#worlds .world').last().scrollIntoViewIfNeeded();
    assert((await page.locator('#worlds .world').last().locator('.mini-planet-image').evaluate(node=>getComputedStyle(node).backgroundImage)).includes('/assets/optimized/'),'last planet must use the preloaded sprite after scrolling');
    const lastRecordScroll=await page.evaluate(()=>({
      scrollY:window.scrollY,
      catalogueScrollTop:document.querySelector('.catalogue').scrollTop,
      catalogue:document.querySelector('.catalogue').getBoundingClientRect().toJSON(),
      searchBottom:document.querySelector('.search').getBoundingClientRect().bottom,
      last:document.querySelector('#worlds .world:last-child').getBoundingClientRect().toJSON(),
      chartTop:document.querySelector('.star-chart').getBoundingClientRect().top,
      destinationTop:document.querySelector('.destination').getBoundingClientRect().top
    }));
    assert.strictEqual(lastRecordScroll.scrollY,0,'browser document must not scroll');
    assert(lastRecordScroll.catalogueScrollTop>0&&lastRecordScroll.searchBottom<lastRecordScroll.catalogue.top,'search and filters must scroll away inside the left panel');
    assert(lastRecordScroll.last.top>=lastRecordScroll.catalogue.top-1&&lastRecordScroll.last.bottom<=lastRecordScroll.catalogue.bottom+1,'last planet must be reachable inside the left-panel scroll area');
    assert(lastRecordScroll.chartTop>=0&&lastRecordScroll.destinationTop>=0,'galaxy and destination panels must remain fixed while the catalogue scrolls');
    await page.evaluate(()=>{document.querySelector('.catalogue').scrollTop=0});
    assert((await page.locator('#worlds .world').first().locator('.mini-planet-image').evaluate(node=>getComputedStyle(node).backgroundImage)).includes('/assets/optimized/'),'first planet thumbnail must remain assigned after scrolling away and back');
    await page.screenshot({path:path.join(__dirname,'validation-header-small.png'),fullPage:false});
    await page.setViewportSize({width:980,height:700});
    await page.waitForFunction(()=>Math.abs(Number(document.querySelector('#archive-shell').dataset.scale)-.7)<.002);
    assert.strictEqual(await page.locator('#archive-shell').getAttribute('data-scale'),'0.7000');
    assert(await page.evaluate(()=>document.documentElement.classList.contains('short-window-layout')),'700 px desktop window must use complete-panel catalogue scrolling');
    const compact=await page.evaluate(()=>{
      const box=selector=>document.querySelector(selector).getBoundingClientRect().toJSON();
      return {console:box('.address-console'),glyphArea:box('.glyph-area'),glyphs:[...document.querySelectorAll('.glyph-box')].map(item=>item.getBoundingClientRect().toJSON()),seal:box('.seal'),selection:box('.selection'),body:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight},scrollY:window.scrollY,catalogueOverflow:getComputedStyle(document.querySelector('.catalogue')).overflowY};
    });
    assert(compact.glyphs.every(glyph=>glyph.width>20&&glyph.height>35&&glyph.top>=compact.glyphArea.top-1&&glyph.bottom<=compact.glyphArea.bottom+1),'all glyphs must remain visible at 980 px');
    assert(compact.glyphArea.bottom<=compact.seal.top+1&&compact.glyphArea.bottom<=compact.selection.top+1,'980 px console must retain the upper/lower split');
    assert.strictEqual(compact.scrollY,0,'980 px archive must not scroll the browser document');
    assert(compact.catalogueOverflow==='auto'&&compact.console.bottom<=701&&compact.body.width<=981&&compact.body.height<=701,'980 px archive must remain inside the browser while the complete catalogue panel scrolls');
    await page.screenshot({path:path.join(__dirname,'validation-console-compact.png'),fullPage:false});
    await page.setViewportSize({width:1408,height:1783});
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.waitForFunction(()=>document.querySelector('#archive-shell').dataset.scale==='1.0000');
    const tall=await page.evaluate(()=>{
      const box=selector=>document.querySelector(selector).getBoundingClientRect().toJSON();
      const worlds=document.querySelector('#worlds');
      return {brand:box('.brand'),nav:box('#integration-nav'),workspace:box('.workspace'),planetScene:box('.planet-scene'),planet:box('#planet'),console:box('.address-console'),worldsScrollable:worlds.scrollHeight>worlds.clientHeight,bodyHeight:document.body.scrollHeight};
    });
    assert(tall.brand.right<=tall.nav.left+1,'tall-window masthead must stay in one non-overlapping row');
    assert(tall.workspace.height>1200,'main panels must expand to use tall-window space');
    assert(tall.planet.left>=tall.planetScene.left-2&&tall.planet.right<=tall.planetScene.right+2&&tall.planet.top>=tall.planetScene.top-2&&tall.planet.bottom<=tall.planetScene.bottom+2,`tall-window planet must stay fully inside its scene: ${JSON.stringify({planet:tall.planet,scene:tall.planetScene})}`);
    assert(tall.console.bottom>=1770&&tall.console.bottom<=1783,'complete address must stay attached to the bottom of a tall window');
    assert(tall.worldsScrollable,'planet list must remain internally scrollable in a tall window');
    assert(tall.bodyHeight<=1783+1,'tall window must not create a long document below the interface');
    await page.screenshot({path:path.join(__dirname,'validation-tall.png'),fullPage:false});
    await page.screenshot({path:path.join(__dirname,'validation-header.png'),fullPage:false});

    const longer=await page.evaluate(()=>{
      const world=window.STELLAR_ARCHIVE_DATA.worlds.find(item=>item.name==='Seed Ship#1');
      document.querySelector(`[data-id="${world.id}"]`).click();
      return {address:world.storedAddress.join('-'),length:world.storedAddress.length,href:document.querySelector('#select-address').getAttribute('href'),consoleName:document.querySelector('#console-destination-name').textContent};
    });
    assert.strictEqual(longer.length,8);
    assert.strictEqual(longer.href,`/receiver.html?address=${longer.address}&source=stellar-archive`);
    assert.strictEqual(longer.consoleName,'SEED SHIP#1');
    assert(!longer.href.includes('-1&')&&!longer.href.endsWith('-1'),'display-only origin must not be appended');

    await page.goto(`http://127.0.0.1:${port}/stellar-archive/`);
    await page.waitForSelector('#select-address');
    const standalone=await page.getAttribute('#select-address','href');
    assert(standalone.startsWith('/receiver.html?address='));
    const standaloneSeed=await page.evaluate(()=>{
      const world=window.STELLAR_ARCHIVE_DATA.worlds.find(item=>item.name==='Seed Ship#1');
      document.querySelector(`[data-id="${world.id}"]`).click();
      return document.querySelector('#select-address').getAttribute('href');
    });
    assert.strictEqual(standaloneSeed,'/receiver.html?address=3-7-11-19-22-30-34-36&source=stellar-archive');

    aquilaInstalled=false;
    addonTask={state:'idle',message:'Ready'};
    addonPolls=0;
    await page.setViewportSize({width:390,height:844});
    await page.goto(`http://127.0.0.1:${port}/stellar-archive/?mode=retro`);
    await page.waitForSelector('#select-address');
    await page.evaluate(()=>sessionStorage.clear());
    await page.waitForFunction(()=>document.documentElement.classList.contains('mobile-layout'));
    const mobile=await page.evaluate(()=>{
      const box=selector=>document.querySelector(selector).getBoundingClientRect().toJSON();
      const worlds=document.querySelector('#worlds');
      return {catalogue:box('.catalogue'),chart:box('.star-chart'),destination:box('.destination'),console:box('.address-console'),body:{width:document.body.scrollWidth,height:document.body.scrollHeight},worlds:{width:worlds.clientWidth,scrollWidth:worlds.scrollWidth},zoom:getComputedStyle(document.querySelector('#archive-shell')).zoom};
    });
    assert.strictEqual(mobile.zoom,'1');
    assert(mobile.catalogue.bottom<=mobile.chart.top+1&&mobile.chart.bottom<=mobile.destination.top+1&&mobile.destination.bottom<=mobile.console.top+1,'phone layout must stack catalogue, galaxy, destination and address console');
    assert(mobile.worlds.scrollWidth>mobile.worlds.width,'phone catalogue must remain horizontally scrollable');
    assert(mobile.body.width<=391,'phone layout must not create horizontal page overflow');
    assert(mobile.body.height>844,'phone layout should use readable vertical scrolling instead of shrinking the desktop canvas');
    await page.screenshot({path:path.join(__dirname,'validation-mobile.png'),fullPage:true});

    await page.getByRole('button',{name:'ABOUT'}).click();
    await page.waitForSelector('#dialog-maintenance:not([hidden])');
    await page.locator('.maintenance-fold').nth(1).locator('summary').click();
    await page.evaluate(()=>{window.open=()=>null});
    await page.locator('#available-addon-list button[data-addon-action="info"]').click();
    assert.strictEqual(await page.locator('#available-addon-list button[data-addon-action="install"]').isDisabled(),false,'GitHub app handoff must unlock INSTALL even when window.open returns null');
    await page.reload();
    await page.waitForSelector('#select-address');
    await page.getByRole('button',{name:'ABOUT'}).click();
    await page.waitForSelector('#dialog-maintenance:not([hidden])');
    await page.locator('.maintenance-fold').nth(1).locator('summary').click();
    const rememberedInstall=page.locator('#available-addon-list button[data-addon-action="install"]');
    await rememberedInstall.waitFor();
    assert.strictEqual(await rememberedInstall.isDisabled(),false,'INFO review must survive return/reload in the same mobile browser session');
    const mobileDialog=await page.locator('#details').evaluate(element=>element.getBoundingClientRect().toJSON());
    assert(mobileDialog.left>=0&&mobileDialog.right<=390&&mobileDialog.top>=0&&mobileDialog.bottom<=844,'mobile maintenance dialog must fit the phone viewport');
    await page.screenshot({path:path.join(__dirname,'validation-mobile-maintenance.png'),fullPage:false});

    console.log('browser integration tests: PASS');
  } finally {
    await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
})().catch(error=>{console.error(error);process.exitCode=1});
