'use strict';
// Read-only local archive. SG1 address-book and local-address APIs are polled only for live gate status.
const archive=window.STELLAR_ARCHIVE_DATA;
const worlds=archive.worlds;
const integrationMode=new URLSearchParams(window.location.search).get('mode');
const integrationNav=window.STELLAR_ARCHIVE_NAV||{mode:'standalone',items:[]};
function configuredHostHomeHref(){
 const host=(window.location.hostname||'').toLowerCase();
 const hostHome=integrationNav.homeByHost&&integrationNav.homeByHost[host];
 return typeof hostHome==='string'&&hostHome.startsWith('/')?hostHome:null;
}
function integrationHomeHref(){
 return configuredHostHomeHref()||(integrationMode==='retro'?'/retro/dial.html':'/index.htm');
}
let selected=worlds[0],visible=[];
let liveGateStatuses=new Map(),liveStatusState='checking',liveStatusSignature='';
const motionEpoch=performance.now();
let motionNodes=[],motionFrame=0,lastMotionUpdate=0;
const reduceMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
const $=selector=>document.querySelector(selector);
const escapeHtml=value=>String(value).replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const glyphPath=n=>`assets/glyphs/milkyway/${String(n).padStart(3,'0')}.svg`;
const fandomSearch=name=>`https://stargate.fandom.com/wiki/Special:Search?query=${encodeURIComponent(name)}`;
const gateWorldProfiles={
 'ABYDOS':'https://www.gateworld.net/wiki/Abydos',
 'DESTROYERS':'https://www.gateworld.net/wiki/Stargate_destroyer',
 'DESTINY':'https://www.gateworld.net/wiki/Destiny',
 'Seed Ship#1':'https://www.gateworld.net/wiki/Ancient_seed_ship'
};
function filtered(){
 const q=$('#search').value.toLowerCase().trim();
 const category=$('#category').value;
 return worlds.filter(w=>(category==='all'||w.category===category)&&`${w.name} ${w.description} ${w.classification} ${w.fullAddress.join('-')}`.toLowerCase().includes(q));
}
const visualClass=world=>`visual-${world.id}`;
const addressKey=address=>address.join('-');
function gateStatus(world){
 const online=liveGateStatuses.get(addressKey(world.storedAddress));
 if(typeof online==='boolean')return {label:online?'ONLINE':'OFFLINE',className:online?'online':'offline'};
 return {label:liveStatusState==='checking'?'CHECKING…':'STATUS UNKNOWN',className:'unknown'};
}
function renderGateSummary(counts){
 $('#online-count').textContent=counts?.online??'—';
 $('#offline-count').textContent=counts?.offline??'—';
 $('#standard-count').textContent=counts?.standard??'—';
 $('#lan-count').textContent=counts?.lan??'—';
}
function worldButton(w){
 const live=gateStatus(w);
 const status=live?`<span class="owner-status ${live.className}">${live.label}</span>`:'';
 const objectClass=w.visualMode==='object'?' object-visual':'';
 return `<button class="world ${w.id===selected.id?'active':''}" data-id="${escapeHtml(w.id)}" aria-pressed="${w.id===selected.id}" aria-label="Explore ${escapeHtml(w.name)}"><span class="mini-planet ${visualClass(w)}${objectClass}" aria-hidden="true"></span><span class="world-text"><span class="world-name">${escapeHtml(w.name)}</span><span class="world-symbols">${w.category.toUpperCase()} · ${w.addressLength} SYMBOLS</span>${status}</span><span class="world-arrow">›</span></button>`;
}
function glyphBox(n,i,total){
 const origin=i===total-1;
 return `<div class="glyph-box ${origin?'origin':''}" aria-label="${origin?'Earth point of origin':`Address symbol ${i+1}`}: glyph ${n}"><img src="${glyphPath(n)}" alt=""><span class="glyph-number">${n}</span></div>`;
}
function render(){
 visible=filtered();
 if(visible.length&&!visible.some(w=>w.id===selected.id))selected=visible[0];
 $('#world-count').textContent=String(visible.length).padStart(3,'0');
 $('#empty').hidden=visible.length>0;
 $('#worlds').innerHTML=visible.map(worldButton).join('');
 if(!visible.length){$('#nodes').innerHTML='';$('#connections').innerHTML='';return;}
 $('#map-galaxy').textContent=selected.galaxy.toUpperCase();
 $('#network-count').textContent=`${selected.addressLength} ADDRESS POINTS`;
 renderAddressPath(selected);
 $('#planet-name').textContent=selected.name;
 $('#console-destination-name').textContent=selected.name.toUpperCase();
 $('#planet-galaxy').textContent=`${selected.galaxy.toUpperCase()} · ${selected.category.toUpperCase()}`;
 $('#planet').className=`planet ${visualClass(selected)}${selected.blackHole&&!selected.visualAsset?' black-hole':''}${selected.visualMode==='object'?' object-visual':''}`;
 $('#designation').textContent=selected.designation;
 $('#environment').textContent=selected.environment;
 $('#archive-class').textContent=selected.classification;
 $('#visual-status').textContent=selected.visualStatus;
 $('#planet-description').textContent=selected.description;
 $('#source-refs').textContent=`Sources: ${selected.sourceRefs.join(' · ')}`;
 $('#planet-research').href=fandomSearch(selected.name);
 const gateWorldUrl=gateWorldProfiles[selected.name];
 $('#gateworld-research').hidden=!gateWorldUrl;
 if(gateWorldUrl)$('#gateworld-research').href=gateWorldUrl;
 $('#record-id').textContent=String(worlds.indexOf(selected)+1).padStart(3,'0');
 $('#evidence-label').textContent=selected.evidenceLevel.replaceAll('-',' ').toUpperCase();
 const live=gateStatus(selected);
 $('#record-state').innerHTML=`<i></i> ${live?live.label:'ARCHIVED'}`;
 $('#glyphs').className=`glyphs glyph-count-${selected.addressLength}`;
 $('#glyphs').innerHTML=selected.fullAddress.map((n,i)=>glyphBox(n,i,selected.fullAddress.length)).join('');
 const correction=selected.addressStatus==='episode-frame-corrected-local'?' · LOCAL FRAME CORRECTION APPLIED':selected.addressStatus==='disputed-source-preserved'?' · DISPUTED SOURCE VALUE PRESERVED':'';
 $('#numeric-address').textContent=`SOURCE STORED: ${selected.storedAddress.join(' · ')}  |  ARCHIVE COMPLETE: ${selected.fullAddress.join(' · ')}  |  ${selected.addressLength} SYMBOLS${correction}`;
 $('#select-address').href=dialHref(selected);
}
function renderAddressPath(world){
 const full=world.fullAddress;
 const references=full.map((glyph,index)=>({glyph,index,slot:archive.glyphPositions[glyph]}));
 $('#nodes').innerHTML=`<button class="node active position-${world.id}" data-id="${escapeHtml(world.id)}" data-base-x="${world.x}" data-base-y="${world.y}" aria-label="Selected destination ${escapeHtml(world.name)}"><span class="node-dot"></span><span class="node-label">${escapeHtml(world.name)}</span></button>`+references.map(({glyph,index,slot})=>{
  const origin=index===full.length-1;
  const label=origin?`ORIGIN · ${glyph}`:`G${index+1} · ${glyph}`;
  const edge=archive.glyphPositions[glyph].x>70?' glyph-edge-right':'';
  return `<div class="node address-node glyph-position-${glyph}${origin?' origin-node':''}${edge}" data-glyph="${glyph}" data-base-x="${slot.x}" data-base-y="${slot.y}" aria-label="${origin?'Earth point of origin':`Address point ${index+1}`}, glyph ${glyph}"><span class="node-dot"></span><span class="node-label">${label}</span></div>`;
 }).join('');
 $('#connections').innerHTML=references.map(({index})=>`<line class="network-link${index===full.length-1?' origin-link':''}"/>`).join('');
 prepareDifferentialMotion();
}
function orbitDuration(radius){
 const normalized=Math.min(1,radius/48);
 return 75+Math.pow(normalized,.82)*165;
}
function prepareDifferentialMotion(){
 motionNodes=[...document.querySelectorAll('#nodes .node')].map(node=>{
  const x=Number(node.dataset.baseX),y=Number(node.dataset.baseY);
  const dx=x-50,dy=y-50;
  return {node,radius:Math.hypot(dx,dy),angle:Math.atan2(dy,dx),duration:orbitDuration(Math.hypot(dx,dy)),x,y};
 });
 updateDifferentialMotion(performance.now());
 if(!reduceMotion.matches&&!motionFrame)motionFrame=requestAnimationFrame(animateDifferentialMotion);
}
function updateDifferentialMotion(now){
 const elapsed=(now-motionEpoch)/1000;
 for(const entry of motionNodes){
  const angle=entry.angle+(Math.PI*2*elapsed/entry.duration);
  entry.x=50+Math.cos(angle)*entry.radius;
  entry.y=50+Math.sin(angle)*entry.radius;
  entry.node.style.left=`${entry.x}%`;
  entry.node.style.top=`${entry.y}%`;
  entry.node.dataset.orbitDuration=entry.duration.toFixed(2);
 }
 const active=motionNodes[0];
 const lines=[...document.querySelectorAll('#connections .network-link')];
 if(active)lines.forEach((line,index)=>{
  const target=motionNodes[index+1];
  if(!target)return;
  line.setAttribute('x1',String(active.x*10));
  line.setAttribute('y1',String(active.y*8));
  line.setAttribute('x2',String(target.x*10));
  line.setAttribute('y2',String(target.y*8));
 });
}
function animateDifferentialMotion(now){
 motionFrame=0;
 if(reduceMotion.matches||document.visibilityState==='hidden')return;
 if(now-lastMotionUpdate>=33){lastMotionUpdate=now;updateDifferentialMotion(now)}
 motionFrame=requestAnimationFrame(animateDifferentialMotion);
}
reduceMotion.addEventListener?.('change',()=>{
 if(reduceMotion.matches&&motionFrame){cancelAnimationFrame(motionFrame);motionFrame=0;updateDifferentialMotion(motionEpoch)}
 else if(!reduceMotion.matches&&!motionFrame)motionFrame=requestAnimationFrame(animateDifferentialMotion);
});
document.addEventListener('visibilitychange',()=>{
 if(document.visibilityState==='visible'&&!reduceMotion.matches&&!motionFrame)motionFrame=requestAnimationFrame(animateDifferentialMotion);
});
function choose(event){const button=event.target.closest('[data-id]');if(!button)return;selected=worlds.find(w=>w.id===button.dataset.id);render()}
$('#worlds').addEventListener('click',choose);
$('#nodes').addEventListener('click',choose);
$('#search').addEventListener('input',render);
$('#category').addEventListener('change',render);
function showDialog(title,copy){$('#dialog-title').textContent=title;$('#dialog-copy').textContent=copy;$('#dialog-maintenance').hidden=true;$('#dialog-links').hidden=true;$('#dialog-links').innerHTML='';$('#details').showModal()}
function dialHref(world){
  const address=world.storedAddress.join('-');
  const hostReceiver=configuredHostHomeHref();
  if(hostReceiver){
    const separator=hostReceiver.includes('?')?'&':'?';
    return `${hostReceiver}${separator}address=${encodeURIComponent(address)}&source=stellar-archive`;
  }
  const dialTarget=integrationMode==='retro'?'retro':integrationMode==='original'?'original':integrationNav.dialTarget;
  if(dialTarget==='v3')return '#';
  if(dialTarget==='retro'){
    const page=world.storedAddress.length>6?'dial9.html':'dial.html';
    return `/retro/${page}?address=${encodeURIComponent(address)}`;
  }
  return `/index.htm?address=${encodeURIComponent(address)}`;
}
$('#select-address').addEventListener('click',async event=>{
 const dialTarget=integrationMode==='retro'?'retro':integrationMode==='original'?'original':integrationNav.dialTarget;
 if(dialTarget!=='v3')return;
 event.preventDefault();
 const button=$('#select-address');
 if(button.dataset.busy==='1')return;
 button.dataset.busy='1';
 try{
  const response=await fetch('/stellar-archive/api/dial',{
   method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({address:selected.storedAddress.join('-')})
  });
  const payload=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(payload.error||`HTTP ${response.status}`);
  window.alert(payload.message||'Dial accepted by SG1_v3');
 }catch(error){window.alert(`Dial failed: ${error.message}`)}
 finally{delete button.dataset.busy}
});
function configureIntegration(){
 $('.brand').href=integrationHomeHref();
 renderIntegrationNav();
}
function fitMastheadContents(){
 const inner=$('.masthead-inner');
 const brand=$('.brand');
 const controls=$('.masthead-controls');
 inner.style.transform='none';
 const naturalWidth=brand.scrollWidth+controls.scrollWidth+24;
 const scale=Math.min(1,inner.clientWidth/naturalWidth);
 inner.style.transform=`scale(${scale})`;
}
function fitArchiveToWindow(){
 const viewport=$('#archive-viewport');
 const shell=$('#archive-shell');
 const width=viewport.clientWidth;
 const height=viewport.clientHeight;
 const mobile=window.matchMedia('(max-width:600px)').matches;
 document.documentElement.classList.toggle('mobile-layout',mobile);
 if(mobile){
  shell.style.zoom='1';
  shell.style.width='100%';
  shell.style.height='auto';
  shell.dataset.scale='1.0000';
  $('.masthead-inner').style.transform='none';
  return;
 }
 const scale=Math.min(1,Math.max(.55,width/1400));
 shell.style.zoom=String(scale);
 shell.style.width=`${width/scale}px`;
 shell.style.height=`${height/scale}px`;
 shell.dataset.scale=scale.toFixed(4);
 fitMastheadContents();
}
function updateInstalledGateName(value){
 const name=String(value||'').trim();
 if(name)$('#installed-gate-name').textContent=name.toUpperCase();
}
function renderIntegrationNav(){
 const nav=$('#integration-nav');
 const items=[...(integrationNav.items||[]).map(item=>String(item.label||'').toUpperCase()==='HOME'?{...item,href:integrationHomeHref()}:item),{label:'ABOUT',action:'about'}];
 nav.innerHTML=items.map(item=>{
  const label=escapeHtml(item.label||'LINK');
  if(item.children?.length)return `<details class="integration-dropdown"><summary class="integration-button">${label}</summary><div class="integration-menu">${item.children.map(child=>navItemHtml(child)).join('')}</div></details>`;
  return navItemHtml(item);
 }).join('');
 nav.addEventListener('click',event=>{
  const button=event.target.closest('[data-nav-action]');
  if(!button)return;
  const action=button.dataset.navAction;
  if(action==='about')showAboutDialog();
  if(['restart','reboot','shutdown'].includes(action))runSystemAction(action);
 });
 fitMastheadContents();
}
function navItemHtml(item){
  const label=escapeHtml(item.label||'LINK');
  if(item.href)return `<a class="integration-button${item.addon?' addon':''}" href="${escapeHtml(item.href)}"${item.title?` title="${escapeHtml(item.title)}"`:''}>${label}</a>`;
  return `<button class="integration-button${item.addon?' addon':''}" type="button" data-nav-action="${escapeHtml(item.action||'')}">${label}</button>`;
}
async function runSystemAction(action){
 const config={restart:['Restart Stargate software?','/stargate/do/restart'],reboot:['Reboot the Raspberry Pi?','/stargate/do/reboot'],shutdown:['Shut down the Raspberry Pi?','/stargate/do/shutdown']}[action];
 if(!config||!window.confirm(config[0]))return;
 try{const response=await fetch(config[1],{method:'POST'});if(!response.ok)throw new Error(`HTTP ${response.status}`)}catch(error){window.alert(`Action failed: ${error.message}`)}
}
const archiveLinks=[
 ['GAIA VISUAL AND SCIENCE','ESA Gaia Milky Way map (2025)','https://www.cosmos.esa.int/web/gaia/milky-way'],
 ['GAIA VISUAL AND SCIENCE','ESA Gaia differential rotation','https://www.cosmos.esa.int/web/gaia/dr3-where-do-the-stars-go-or-come-from'],
 ['GAIA VISUAL AND SCIENCE','CC BY-SA 3.0 IGO licence','https://creativecommons.org/licenses/by-sa/3.0/igo/'],
 ['PORTALS AND ENCYCLOPEDIAS','Stargate Wiki','https://stargate.fandom.com/wiki/Stargate_Wiki'],
 ['PORTALS AND ENCYCLOPEDIAS','Stargate Fandom','https://stargate.fandom.com/'],
 ['PORTALS AND ENCYCLOPEDIAS','GateWorld','https://www.gateworld.net/'],
 ['PORTALS AND ENCYCLOPEDIAS','Richard Dean Anderson','https://www.rdanderson.com/'],
 ['PORTALS AND ENCYCLOPEDIAS','Stargate SG-1 Solutions','https://www.stargate-sg1-solutions.com/'],
 ['PORTALS AND ENCYCLOPEDIAS','GateWorld Wiki','https://www.gateworld.net/wiki/Main_Page'],
 ['PORTALS AND ENCYCLOPEDIAS','SG-1 Solutions Wiki','https://www.stargate-sg1-solutions.com/wiki/Main_Page'],
 ['PORTALS AND ENCYCLOPEDIAS','Stargate Wiki (NOIP)','https://en.stargatewiki.noip.me/'],
 ['PORTALS AND ENCYCLOPEDIAS','Neoseeker Stargate Wiki','https://stargate.neoseeker.com/wiki/Main_Page'],
 ['PORTALS AND ENCYCLOPEDIAS','Save Stargate','https://savestargate.com/'],
 ['INTERNATIONAL WEBSITES','Stargate Fusion','https://www.stargate-fusion.com/'],
 ['INTERNATIONAL WEBSITES','Stargate Initiative','https://www.stargateinitiative.com/'],
 ['INTERNATIONAL WEBSITES','Stargate Project Germany','https://www.stargate-project.de/'],
 ['INTERNATIONAL WEBSITES','Stargate Project Fansites','https://www.stargate-project.de/stargate-fansites'],
 ['INTERNATIONAL WEBSITES','Stargate Initiative Community','https://www.stargateinitiative.com/communaute'],
 ['REPLICAS, PROPS, AND FORUMS','SG-1 Props','https://www.sg1props.com/'],
 ['REPLICAS, PROPS, AND FORUMS','SG-1 Props Forum','https://www.sg1props.com/forums/viewforum.php?f=2'],
 ['REPLICAS, PROPS, AND FORUMS','GateWorld Forum','https://forum6.gateworld.net/'],
 ['ARCHIVES AND DIRECTORIES','Websites and Wikis Archive','https://stargate.fandom.com/wiki/Websites_and_wikis'],
 ['ARCHIVES AND DIRECTORIES','SG-1 Solutions Archive','https://stargate-sgc.fandom.com/wiki/Stargate_SG-1_Solutions'],
 ['ARCHIVES AND DIRECTORIES','Squidge SGA Links','https://classic.squidge.org/fictionr/sga/links.php'],
 ['ADDITIONAL PAGES','SG-1 Props Catalogue','https://www.sg1props.com/props'],
 ['ADDITIONAL PAGES','GateWorld FAQ','https://www.gateworld.net/faq'],
 ['ADDITIONAL PAGES','GateWorld Site History','https://www.gateworld.net/site-history/']
];
function showAboutDialog(){
 $('#dialog-title').textContent='STARGATE · LIST OF WEBSITES';
 $('#dialog-copy').textContent=`A local archive of ${archive.count} destinations. Galaxy visual adapted from ESA/Gaia/DPAC and Stefan Payne-Wardenaar, CC BY-SA 3.0 IGO. Differential motion is accelerated and illustrative; destination coordinates are not Gaia measurements. Some archived external links may no longer work.`;
 const links=$('#dialog-links');
 let section='';
 links.innerHTML=archiveLinks.map(([category,label,url])=>{const heading=category===section?'':`<h3>${escapeHtml(category)}</h3>`;section=category;return `${heading}<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} <span>↗</span></a>`}).join('');
 links.hidden=false;
 $('#dialog-maintenance').hidden=false;
 $('#details').showModal();
 loadInstalledAddons();
}
async function maintenanceRequest(url,options={}){
 const headers={...(options.headers||{}),'X-Stellar-Archive-Request':'same-origin'};
 const response=await fetch(url,{cache:'no-store',credentials:'same-origin',...options,headers});
 const payload=await response.json().catch(()=>({success:false,message:`HTTP ${response.status}`}));
 if(!response.ok||payload.success===false)throw new Error(payload.message||`HTTP ${response.status}`);
 return payload;
}
function setMaintenanceBusy(busy,message){
 $('#check-archive-update').disabled=busy;
 $('#uninstall-archive').disabled=busy;
 if(message)$('#maintenance-status').textContent=message;
}
let installedAddons=[];
let availableAddons=[];
const reviewedAddonRepositories=new Set();
const reviewedAddonStorageKey='stellar-archive-reviewed-addons-v1';
try{
 for(const id of JSON.parse(sessionStorage.getItem(reviewedAddonStorageKey)||'[]'))reviewedAddonRepositories.add(String(id));
}catch(error){}
function rememberReviewedAddon(id){
 reviewedAddonRepositories.add(id);
 try{sessionStorage.setItem(reviewedAddonStorageKey,JSON.stringify([...reviewedAddonRepositories]))}catch(error){}
}
function addonRevision(value){return value?escapeHtml(value):'UNKNOWN'}
function renderAddons(addons,available){
 installedAddons=addons||[];
 availableAddons=available||[];
 const host=$('#addon-list');
 $('#installed-addon-count').textContent=`(${installedAddons.length+1})`;
 $('#available-addon-count').textContent=`(${availableAddons.length})`;
 $('#addon-manager-status').textContent=installedAddons.length?`${installedAddons.length} supported matelv-x add-on${installedAddons.length===1?'':'s'} detected.`:'No supported matelv-x add-ons are currently installed.';
 host.innerHTML=installedAddons.map(addon=>{
  const task=addon.task||{};
  const running=task.state==='running';
  let state=addon.check_error?`Update check unavailable: ${addon.check_error}`:(addon.update_available===true?'UPDATE AVAILABLE':(addon.update_available===false?'UP TO DATE':'INSTALLED VERSION UNKNOWN'));
  if(!addon.can_uninstall)state+=` · SAFE AUTOMATIC UNINSTALL UNAVAILABLE`;
  if(task.message&&task.state!=='idle')state=task.message;
  const updateDisabled=running||!addon.can_update;
  const uninstallDisabled=running||!addon.can_uninstall;
  return `<article class="addon-row" data-addon-id="${escapeHtml(addon.id)}"><div class="addon-row-head"><div><a class="addon-row-name" href="${escapeHtml(addon.repository_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(addon.name)} ↗</a><div class="addon-row-meta${addon.check_error?' error':''}">${escapeHtml(state)} · LOCAL ${addonRevision(addon.current_revision)} · GITHUB ${addonRevision(addon.latest_revision)}</div></div></div><div class="dialog-actions"><button type="button" data-addon-action="update" ${updateDisabled?'disabled':''}>CHECK FOR UPDATES</button><button type="button" class="danger" data-addon-action="uninstall" ${uninstallDisabled?'disabled':''}>UNINSTALL</button></div></article>`
 }).join('');
 $('#available-addon-list').innerHTML=availableAddons.map(addon=>{
  const reviewed=reviewedAddonRepositories.has(addon.id);
  const safe=addon.can_install;
  const task=addon.task||{};
  const running=task.state==='running';
  const state=task.message&&task.state!=='idle'?task.message:(addon.check_error?`Repository unavailable: ${addon.check_error}`:(safe?'SAFE UNINSTALL VERIFIED':'INSTALLATION BLOCKED · SAFE UNINSTALL REQUIRED'));
  return `<article class="addon-row" data-addon-id="${escapeHtml(addon.id)}"><div class="addon-row-head"><div><span class="addon-row-name">${escapeHtml(addon.name)}</span><div class="addon-row-meta${addon.check_error||!safe?' error':''}">${escapeHtml(state)} · GITHUB ${addonRevision(addon.latest_revision)}</div></div></div><div class="dialog-actions"><button type="button" class="addon-info" data-addon-action="info" aria-label="Open ${escapeHtml(addon.name)} repository information">ⓘ INFO</button><button type="button" data-addon-action="install" ${running||!reviewed||!safe||!!addon.check_error?'disabled':''}>INSTALL</button></div></article>`;
 }).join('');
}
async function loadInstalledAddons(){
 $('#refresh-addons').disabled=true;
 $('#addon-manager-status').textContent='Detecting installed add-ons and checking GitHub…';
 try{
  const payload=await maintenanceRequest('/stargate/get/stellar_archive_addons');
  renderAddons(payload.addons||[],payload.available||[]);
 }catch(error){
  $('#addon-manager-status').textContent=`Add-on detection failed: ${error.message}`;
 }finally{$('#refresh-addons').disabled=false}
}
let addonProgressContext=null;
const addonProgressPhases=['download','verify','install','complete'];
function showAddonProgress(addon,action){
 addonProgressContext={id:addon.id,name:addon.name,action,restartRequired:Boolean(addon.restart_required)};
 const overlay=$('#addon-progress-overlay');
 overlay.hidden=false;
 overlay.dataset.running='true';
 overlay.dataset.state='running';
 $('#addon-progress-title').textContent=`${action.toUpperCase()} IN PROGRESS`;
 $('#addon-progress-name').textContent=addon.name;
 $('#addon-progress-status').textContent='Preparing secure operation…';
 $('#addon-progress-bar').style.width='5%';
 $('#addon-progress-close').hidden=true;
 $('#addon-progress-restart').hidden=true;
 updateAddonProgressSteps('prepare');
}
function updateAddonProgressSteps(phase){
 const activeIndex=addonProgressPhases.indexOf(phase);
 document.querySelectorAll('.addon-progress-steps li').forEach(item=>{
  const index=addonProgressPhases.indexOf(item.dataset.phase);
  item.classList.toggle('active',index===activeIndex);
  item.classList.toggle('done',activeIndex>=0&&index<activeIndex);
 });
}
function updateAddonProgress(task){
 if(!addonProgressContext)return;
 const overlay=$('#addon-progress-overlay');
 const phase=task.phase||(task.state==='complete'?'complete':task.state==='failed'?'failed':'prepare');
 const progress=Number.isFinite(Number(task.progress))?Math.max(5,Math.min(100,Number(task.progress))):5;
 overlay.dataset.running=String(task.state==='running');
 overlay.dataset.state=task.state||'running';
 $('#addon-progress-bar').style.width=`${progress}%`;
 $('#addon-progress-status').textContent=task.message||'Operation in progress…';
 updateAddonProgressSteps(phase);
 if(task.state==='complete'){
  $('#addon-progress-title').textContent=`${addonProgressContext.action.toUpperCase()} COMPLETE`;
  $('#addon-progress-close').textContent=addonProgressContext.restartRequired?'LATER':'CLOSE';
  $('#addon-progress-close').hidden=false;
  $('#addon-progress-restart').hidden=!addonProgressContext.restartRequired;
 }else if(task.state==='failed'){
  $('#addon-progress-title').textContent=`${addonProgressContext.action.toUpperCase()} FAILED`;
  $('#addon-progress-close').textContent='CLOSE';
  $('#addon-progress-close').hidden=false;
  $('#addon-progress-restart').hidden=true;
 }
}
function failAddonProgress(message){
 updateAddonProgress({state:'failed',phase:'failed',progress:100,message});
}
async function pollAddonMaintenance(addonId){
 for(let attempt=0;attempt<300;attempt++){
  await new Promise(resolve=>window.setTimeout(resolve,1000));
  try{
   const payload=await maintenanceRequest('/stargate/get/stellar_archive_addons');
   renderAddons(payload.addons||[],payload.available||[]);
   const addon=[...(payload.addons||[]),...(payload.available||[])].find(item=>item.id===addonId);
   if(!addon){failAddonProgress('The add-on status is no longer available.');return}
   updateAddonProgress(addon.task||{});
   if(['complete','failed'].includes(addon.task?.state))return;
  }catch(error){$('#addon-manager-status').textContent=`Add-on status unavailable: ${error.message}`;failAddonProgress(`Status unavailable: ${error.message}`);return}
 }
 $('#addon-manager-status').textContent='The add-on operation is still running. Refresh in a moment.';
 failAddonProgress('The operation did not report completion. Check the installed add-on list before trying again.');
}
$('#addon-progress-close').addEventListener('click',()=>{$('#addon-progress-overlay').hidden=true;addonProgressContext=null;loadInstalledAddons()});
$('#addon-progress-restart').addEventListener('click',async()=>{
 if(!addonProgressContext||!window.confirm(`Restart the Stargate service for ${addonProgressContext.name} now?`))return;
 $('#addon-progress-close').hidden=true;
 $('#addon-progress-restart').hidden=true;
 $('#addon-progress-overlay').dataset.running='true';
 $('#addon-progress-title').textContent='RESTARTING SERVICE';
 $('#addon-progress-status').textContent='Sending a target-specific restart request…';
 try{
  await maintenanceRequest('/stargate/do/stellar_archive_restart',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  $('#addon-progress-status').textContent='Restart requested. Waiting for the Stargate service…';
  await new Promise(resolve=>window.setTimeout(resolve,1500));
  let online=false;
  for(let attempt=0;attempt<60;attempt++){
   try{await maintenanceRequest('/stargate/get/stellar_archive_update');online=true;break}catch(error){await new Promise(resolve=>window.setTimeout(resolve,1000))}
  }
  if(!online)throw new Error('the service did not return within 60 seconds');
  $('#addon-progress-overlay').dataset.running='false';
  $('#addon-progress-title').textContent='SERVICE ONLINE';
  $('#addon-progress-status').textContent='The correct Stargate service restarted successfully.';
  $('#addon-progress-close').textContent='CLOSE';
  $('#addon-progress-close').hidden=false;
 }catch(error){failAddonProgress(`Restart failed: ${error.message}`)}
});
$('#refresh-addons').addEventListener('click',loadInstalledAddons);
async function handleAddonAction(event){
 const button=event.target.closest('button[data-addon-action]');
 if(!button)return;
 const row=button.closest('[data-addon-id]');
 const addonId=row?.dataset.addonId;
 const action=button.dataset.addonAction;
 let addon=[...installedAddons,...availableAddons].find(item=>item.id===addonId);
 if(!addon)return;
 if(action==='info'){
  // Record the user's explicit INFO action before leaving the browser. Mobile
  // systems often hand the URL to the GitHub app and return null from
  // window.open(), even though the information opened successfully.
  rememberReviewedAddon(addon.id);
  renderAddons(installedAddons,availableAddons);
  $('#addon-manager-status').textContent=`${addon.name} information opened. INSTALL is now available.`;
  const opened=window.open(addon.repository_url,'_blank');
  if(opened!==null){try{opened.opener=null}catch(error){}}
  return;
 }
 if(action==='update'){
  await loadInstalledAddons();
  addon=installedAddons.find(item=>item.id===addonId);
  if(!addon)return;
  if(addon.check_error){$('#addon-manager-status').textContent=`${addon.name}: ${addon.check_error}`;return}
  if(addon.update_available===false){$('#addon-manager-status').textContent=`${addon.name} is up to date.`;return}
  const question=addon.update_available===true
   ?`Update ${addon.name} from ${addon.current_revision||'unknown'} to ${addon.latest_revision||'latest'}?`
   :`The installed ${addon.name} revision is unknown. Install the latest GitHub revision ${addon.latest_revision||''}?`;
  if(!window.confirm(question))return;
 }else if(action==='install'){
  if(!reviewedAddonRepositories.has(addon.id)){ $('#addon-manager-status').textContent='Open the information link before installation.';return }
  if(!addon.can_install){$('#addon-manager-status').textContent=`${addon.name} cannot be installed until a safe uninstall procedure is verified.`;return}
  if(!window.confirm(`Install ${addon.name} from its verified matelv-x repository? A Stargate software restart may be required afterward.`))return;
 }else if(!window.confirm(`Uninstall ${addon.name} using its verified bounded restore procedure?`))return;
 button.disabled=true;
 $('#addon-manager-status').textContent=`Starting ${action} for ${addon.name}…`;
 showAddonProgress(addon,action);
 try{
  const payload=await maintenanceRequest(`/stargate/do/stellar_archive_addon_${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:addonId})});
  $('#addon-manager-status').textContent=payload.message||`${action} started.`;
  updateAddonProgress(payload.task||{state:'running',phase:'prepare',progress:5,message:payload.message});
  pollAddonMaintenance(addonId);
 }catch(error){$('#addon-manager-status').textContent=`${addon.name}: ${error.message}`;button.disabled=false;failAddonProgress(error.message)}
}
$('#addon-list').addEventListener('click',handleAddonAction);
$('#available-addon-list').addEventListener('click',handleAddonAction);
async function pollMaintenance(){
 for(let attempt=0;attempt<180;attempt++){
  await new Promise(resolve=>window.setTimeout(resolve,2000));
  try{
   const payload=await maintenanceRequest('/stargate/get/stellar_archive_update');
   const task=payload.task||{};
   if(task.message)$('#maintenance-status').textContent=task.message;
   if(task.state==='complete'||task.state==='failed'){setMaintenanceBusy(false,task.message);return}
  }catch(error){setMaintenanceBusy(false,`Maintenance status unavailable: ${error.message}`);return}
 }
 setMaintenanceBusy(false,'Maintenance is still running. Check again in a moment.');
}
$('#check-archive-update').addEventListener('click',async()=>{
 setMaintenanceBusy(true,'Checking the GitHub release…');
 try{
  const status=await maintenanceRequest('/stargate/get/stellar_archive_update');
  if(!status.update_available){setMaintenanceBusy(false,`Stellar Archive ${status.current_version} is up to date.`);return}
  if(!window.confirm(`Update Stellar Archive ${status.current_version} to ${status.latest_version}?`)){setMaintenanceBusy(false,'Update cancelled.');return}
  const result=await maintenanceRequest('/stargate/do/stellar_archive_update',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  setMaintenanceBusy(true,result.message||'Update started…');
  pollMaintenance();
 }catch(error){setMaintenanceBusy(false,`Update check failed: ${error.message}`)}
});
$('#uninstall-archive').addEventListener('click',async()=>{
 if(!window.confirm('Uninstall Stellar Archive and restore the files captured before installation?'))return;
 setMaintenanceBusy(true,'Starting uninstall…');
 try{
  const result=await maintenanceRequest('/stargate/do/stellar_archive_uninstall',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  setMaintenanceBusy(true,result.message||'Uninstall started…');
  pollMaintenance();
 }catch(error){setMaintenanceBusy(false,`Uninstall failed: ${error.message}`)}
});
$('#close-dialog').addEventListener('click',()=>$('#details').close());
$('#details').addEventListener('click',event=>{if(event.target===$('#details')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close()}});
async function refreshGateStatuses(){
 const controller=new AbortController();
 const timeout=window.setTimeout(()=>controller.abort(),5000);
 try{
  const request={cache:'no-store',credentials:'same-origin',signal:controller.signal};
  const [bookResponse,statusResponse]=await Promise.all([
   fetch('/stargate/get/address_book?type=all',request),
   fetch('/stargate/get/dialing_status',request)
  ]);
  if(!bookResponse.ok||!statusResponse.ok)throw new Error(`HTTP ${bookResponse.status}/${statusResponse.status}`);
  const [payload,dialingStatus]=await Promise.all([bookResponse.json(),statusResponse.json()]);
  updateInstalledGateName(dialingStatus.gate_name);
  const entries=Object.values(payload.address_book||{});
  const localAddress=Array.isArray(dialingStatus.local_address)?addressKey(dialingStatus.local_address):'';
  const v3=dialingStatus.platform==='sg1_v3'||payload.platform==='sg1_v3';
  const counts={online:v3?'—':0,offline:v3?'—':0,standard:0,lan:0};
  for(const entry of entries){
   if(!Array.isArray(entry.gate_address))continue;
   if(entry.type==='standard'){counts.standard++;continue}
   if(entry.type==='lan'){counts.lan++;continue}
   if(entry.type!=='fan'||v3)continue;
   const online=addressKey(entry.gate_address)===localAddress||String(entry.is_gate_online)==='1';
   counts[online?'online':'offline']++;
  }
  const statusEntries=v3?entries.filter(entry=>Array.isArray(entry.gate_address)&&addressKey(entry.gate_address)===localAddress):entries.filter(entry=>Array.isArray(entry.gate_address));
  const next=new Map(statusEntries.map(entry=>[
   addressKey(entry.gate_address),addressKey(entry.gate_address)===localAddress||String(entry.is_gate_online)==='1'
  ]));
  if(!next.size)throw new Error('empty address book');
  const signature=[...next].sort(([a],[b])=>a.localeCompare(b)).map(([address,online])=>`${address}:${online?1:0}`).join('|');
  liveGateStatuses=next;
  liveStatusState='ready';
  renderGateSummary(counts);
  if(signature!==liveStatusSignature){liveStatusSignature=signature;render()}
 }catch(error){
  if(liveStatusState!=='error'){liveGateStatuses=new Map();liveStatusState='error';liveStatusSignature='';renderGateSummary(null);render()}
 }finally{window.clearTimeout(timeout)}
}
configureIntegration();
fitArchiveToWindow();
window.addEventListener('resize',fitArchiveToWindow,{passive:true});
window.visualViewport?.addEventListener('resize',fitArchiveToWindow,{passive:true});
render();
refreshGateStatuses();
window.setInterval(refreshGateStatuses,15000);
