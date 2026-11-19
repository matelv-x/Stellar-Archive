// Loads revisioned catalogue content before starting the stable Archive app.
(async()=>{
 const packagedRevision='2026-11-19.1';
 const controller=new AbortController();
 const timeout=window.setTimeout(()=>controller.abort(),1500);
 let revision=packagedRevision;
 try{
  const response=await fetch('/stargate/get/stellar_archive_catalogue',{cache:'no-store',credentials:'same-origin',signal:controller.signal});
  if(response.ok){
   const payload=await response.json();
   if(payload?.catalogue?.revision)revision=String(payload.catalogue.revision);
  }
 }catch(error){}finally{window.clearTimeout(timeout)}
 const suffix=`catalogue=${encodeURIComponent(revision)}`;
 const loadStyle=href=>new Promise((resolve,reject)=>{
  const link=document.createElement('link');
  link.rel='stylesheet';link.href=`${href}?${suffix}`;link.onload=resolve;link.onerror=reject;
  document.head.append(link);
 });
 const loadScript=src=>new Promise((resolve,reject)=>{
  const script=document.createElement('script');
  script.src=src;script.onload=resolve;script.onerror=reject;
  document.body.append(script);
 });
 await Promise.all([loadStyle('thumbnail-sprite.css'),loadStyle('world-styles.css')]);
 await loadScript(`data/worlds.js?${suffix}`);
 await loadScript('data/integration-nav.js?v=sg1-universal-1.5.37');
 await loadScript('app.js?v=sg1-universal-1.5.37-catalogue-content-1');
 document.documentElement.dataset.catalogueReady=revision;
})().catch(error=>{
 const message=document.createElement('p');
 message.className='catalogue-load-error';
 message.textContent=`Stellar Archive catalogue could not be loaded: ${error.message}`;
 document.body.append(message);
});
