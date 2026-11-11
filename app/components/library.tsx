'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { translations, type Language } from './i18n';

type Entry={id:string;document_id:string;page_pdf:number;page_printed:string|null;title_de:string;title_es:string;title_en:string;typology:string;spaces:string[];activities:string[];equipment:string[];dimensions:{nombre:string;valor:number;unidad:string;contexto:string}[];bbox:number[];figures:{path:string;bbox:number[];kind:string}[];text:string;snippet?:string;confidence:number;needs_review:number};
type Results={results:Entry[];total:number;facets:Record<string,Record<string,number>>;terms:string[];mode:string;warnings:string[];interpretation:{query_de:string;typology:string|null}|null};
type Status={entries:number;review:number;vectors:number;llm_available:boolean;documents:{id:string;page_count:number;processed_pages:number}[]};
type Collection={id:string;name:string;count:number};
type Page={number:number;printed:string|null;width:number;height:number;image:string;page_count:number;tables_json:{bbox:number[];rows:(string|null)[][]}[]};
type Filters=Record<string,string>;
const blank:Filters={typology:'',space:'',activity:'',equipment:'',min_cm:'',max_cm:'',review:''};
async function api<T>(path:string,options?:RequestInit):Promise<T>{
 const response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...options?.headers}});
 if(!response.ok) throw new Error(`HTTP ${response.status}`);
 return response.json();
}
const image=(path:string)=>'/api/assets/'+path.split('/').map(encodeURIComponent).join('/');
function Highlight({text,terms}:{text:string;terms:string[]}){
 const words=terms.filter(Boolean).sort((a,b)=>b.length-a.length);
 if(!words.length)return <>{text}</>;
 const expression=new RegExp('('+words.map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')','gi');
 return <>{text.split(expression).map((part,i)=>i%2?<mark key={i}>{part}</mark>:part)}</>;
}
export default function Library(){
 const [lang,setLang]=useState<Language>('es'); const t=translations[lang];
 const [view,setView]=useState('library');const [q,setQ]=useState('');const [filters,setFilters]=useState<Filters>(blank);
 const [natural,setNatural]=useState(false);const [results,setResults]=useState<Results|null>(null);
 const [status,setStatus]=useState<Status|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const [detail,setDetail]=useState<Entry|null>(null);const [favorites,setFavorites]=useState<Entry[]>([]);
 const [collections,setCollections]=useState<Collection[]>([]);const [collection,setCollection]=useState<{id:string;name:string;entries:Entry[]}|null>(null);
 const [newName,setNewName]=useState('');const [categoryList,setCategoryList]=useState<{typology:string;count:number}[]>([]);
 const [viewer,setViewer]=useState<Page|null>(null);const [viewerDoc,setViewerDoc]=useState('');const [viewerEntry,setViewerEntry]=useState<Entry|null>(null);
 const [pageInput,setPageInput]=useState('1');const [zoom,setZoom]=useState(100);const [figure,setFigure]=useState('');
 const [featured,setFeatured]=useState<Entry[]>([]);const [featuredIndex,setFeaturedIndex]=useState(0);
 const dialog=useRef<HTMLDialogElement>(null);const heading=useRef<HTMLHeadingElement>(null);const request=useRef<AbortController|null>(null);
 const offset=useRef(0);
 const [toc,setToc]=useState<Record<string,[number,string,number][]>>({});
 const handleError=(e:unknown)=>setError(e instanceof Error?e.message:'Request failed');
 const run=async(action:()=>Promise<unknown>)=>{setError('');try{await action();}catch(e){handleError(e);}};
 const load=useCallback(async(query:string,f:Filters,nat:boolean,skip=0)=>{
  request.current?.abort();const controller=new AbortController();request.current=controller;setBusy(true);setError('');
  const params=new URLSearchParams({q:query,natural:String(nat),offset:String(skip)});
  Object.entries(f).forEach(([k,v])=>{if(v)params.set(k,v);});
  try{const data=await api<Results>('/search?'+params,{signal:controller.signal});if(!controller.signal.aborted){setResults(data);offset.current=skip;}}
  catch(e){if(!controller.signal.aborted)handleError(e);}finally{if(!controller.signal.aborted)setBusy(false);}
 },[]);
 const refreshPersonal=async()=>{
  const [f,c]=await Promise.all([api<Entry[]>('/favorites'),api<Collection[]>('/collections')]);setFavorites(f);setCollections(c);
 };
 const openDetail=async(id:string,push=true)=>{
  const item=await api<Entry>('/entries/'+encodeURIComponent(id));setDetail(item);setView('detail');
  if(push)history.pushState({},'', '?entry='+encodeURIComponent(id));
 };
 useEffect(()=>{
  const saved=localStorage.getItem('neufert-language');if(saved&&saved in translations)setLang(saved as Language);
  void run(async()=>{
   const [s,c,first]=await Promise.all([api<Status>('/status'),api<{typology:string;count:number}[]>('/index'),api<Results>('/search?limit=5')]);
   setStatus(s);setCategoryList(c);setFeatured(first.results);await refreshPersonal();
   const outlines=await Promise.all(s.documents.map(async doc=>[doc.id,await api<[number,string,number][]>('/documents/'+doc.id+'/toc')] as const));setToc(Object.fromEntries(outlines));
   const params=new URLSearchParams(location.search);const search=params.get('q')||'';setQ(search);
   const f={...blank};Object.keys(f).forEach(k=>{f[k]=params.get(k)||'';});setFilters(f);
   await load(search,f,false);
   if(params.get('entry'))await openDetail(params.get('entry')!,false);
  });
  const pop=()=>void run(async()=>{
   const params=new URLSearchParams(location.search);
   if(params.get('entry'))await openDetail(params.get('entry')!,false);
   else{setView('library');const search=params.get('q')||'';setQ(search);const f={...blank};Object.keys(f).forEach(k=>f[k]=params.get(k)||'');setFilters(f);await load(search,f,false);}
  });
  window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);
 },[load]);
 useEffect(()=>{document.documentElement.lang=lang;},[lang]);
 useEffect(()=>{heading.current?.focus();},[view,detail?.id]);
 useEffect(()=>{if(figure)dialog.current?.showModal();},[figure]);
 const navigate=(next:string)=>{setView(next);setError('');if(next!=='detail')history.pushState({},'','/');};
 const searchNow=(f=filters,query=q,nat=natural)=>{
  setView('library');setFilters(f);const params=new URLSearchParams({q:query});Object.entries(f).forEach(([k,v])=>{if(v)params.set(k,v);});history.pushState({},'','?'+params);void load(query,f,nat);
 };
 const openPage=async(doc:string,number:number,entry:Entry|null=null)=>{
  const page=await api<Page>(`/documents/${encodeURIComponent(doc)}/pages/${number}`);
  setViewer(page);setViewerDoc(doc);setViewerEntry(entry);setPageInput(String(number));setZoom(100);setView('viewer');
 };
 const favorite=async(item:Entry)=>{await api('/favorites/'+item.id,{method:'PUT',body:JSON.stringify({favorite:!favorites.some(f=>f.id===item.id)})});await refreshPersonal();};
 const openCollection=async(id:string)=>{setCollection(await api('/collections/'+id));};
 const favoriteButton=(item:Entry)=><button onClick={()=>void run(()=>favorite(item))} aria-pressed={favorites.some(f=>f.id===item.id)}>{favorites.some(f=>f.id===item.id)?t.unfavorite:t.favorite}</button>;
 const reference=(item:Entry)=><p>{t.page} {item.page_pdf} · {t.printed}: {item.page_printed||t.unknown}</p>;
 const card=(item:Entry)=><article key={item.id}>
  <h3><a href={'?entry='+item.id} onClick={e=>{e.preventDefault();void run(()=>openDetail(item.id));}} lang="de">{item.title_de}</a></h3>
  {item.figures[0]&&<img src={image(item.figures[0].path)} width="240" alt={`${t.figure} · ${t.page} ${item.page_pdf}`} loading="lazy"/>}
  <p lang="de"><Highlight text={item.snippet||item.text.slice(0,300)} terms={results?.terms||[]}/></p>
  {reference(item)}{item.needs_review>0&&<p>{t.reviewNeeded} ({Math.round(item.confidence*100)}%)</p>}
  {favoriteButton(item)}
 </article>;
 return <>
  <a href="#main">{t.library} ⭢</a>
  <header><nav aria-label="Neufert"><a href="/" onClick={e=>{e.preventDefault();navigate('library');}}>neufert</a>{' · '}
   {(['library','categories','collections','about'] as const).map((name,i)=><span key={name}><a href={'#'+name} aria-current={view===name?'page':undefined} onClick={e=>{e.preventDefault();navigate(name);}}>{t[name]}</a>{i<3?' · ':''}</span>)}
  </nav><label>{t.language} <select value={lang} onChange={e=>{setLang(e.target.value as Language);localStorage.setItem('neufert-language',e.target.value);}}><option value="es">ES</option><option value="en">EN</option><option value="de">DE</option></select></label></header>
  <main id="main">
   <h1 ref={heading} tabIndex={-1}>{view==='detail'?detail?.title_de:view==='viewer'?`${t.page} ${viewer?.number}`:view==='library'?'Neufert Digital':t[view as 'categories'|'collections'|'about']}</h1>
   {error&&<div role="alert"><p>{t.failure} ({error})</p><button onClick={()=>void run(async()=>{setStatus(await api('/status'));await load(q,filters,natural);await refreshPersonal();})}>{t.retry}</button></div>}
   {status?.entries===0&&<p role="status">{t.noBook}</p>}
   {view==='library'&&<>
    {!q&&featured.length>0&&<section aria-label={t.featured}><h2>{t.featured}</h2><figure>
     {featured[featuredIndex].figures[0]?<img width="300" src={image(featured[featuredIndex].figures[0].path)} alt={featured[featuredIndex].title_de}/>:<p lang="de">{featured[featuredIndex].text.slice(0,240)}</p>}
     <figcaption lang="de">{featured[featuredIndex].title_de} · {t.page} {featured[featuredIndex].page_pdf}</figcaption></figure>
     <button aria-label={t.previous} onClick={()=>setFeaturedIndex((featuredIndex+featured.length-1)%featured.length)}>←</button>{' '}
     <button aria-label={t.next} onClick={()=>setFeaturedIndex((featuredIndex+1)%featured.length)}>→</button>{' '}
     <button onClick={()=>void run(()=>openDetail(featured[featuredIndex].id))}>{t.open}</button></section>}
    <form role="search" onSubmit={e=>{e.preventDefault();searchNow();}}>
     <label htmlFor="query">{t.query}</label>{' '}<input id="query" type="search" value={q} maxLength={1000} placeholder={t.placeholder} onChange={e=>setQ(e.target.value)}/>{' '}<button type="submit" disabled={busy}>{t.search} ⭢</button>
     <p><label><input type="checkbox" checked={natural} onChange={e=>setNatural(e.target.checked)}/>{t.natural}</label></p><p>{t.privacy}</p>
     <fieldset><legend>{t.categories}</legend>
      {(['typology','space','activity','equipment'] as const).map(key=><p key={key}><label htmlFor={key}>{t[key]} </label><select id={key} value={filters[key]} onChange={e=>searchNow({...filters,[key]:e.target.value})}><option value="">{t.all}</option>
       {filters[key]&&!results?.facets[key]?.[filters[key]]&&<option value={filters[key]}>{filters[key]} (0)</option>}
       {Object.entries(results?.facets[key]||{}).map(([value,count])=><option key={value} value={value}>{value} ({count})</option>)}</select></p>)}
      <p>{t.dimensionsHelp}</p><label>{t.min} <input type="number" min="0" step="any" value={filters.min_cm} onChange={e=>setFilters({...filters,min_cm:e.target.value})}/></label>{' '}
      <label>{t.max} <input type="number" min="0" step="any" value={filters.max_cm} onChange={e=>setFilters({...filters,max_cm:e.target.value})}/></label>
      <p><label><input type="checkbox" checked={!!filters.review} onChange={e=>searchNow({...filters,review:e.target.checked?'true':''})}/>{t.review}</label></p>
      <button type="button" onClick={()=>searchNow({...blank})}>{t.clear}</button>
     </fieldset>
    </form>
    <section aria-busy={busy} aria-labelledby="results"><h2 id="results">{t.results}</h2><p role="status" aria-live="polite">{busy?t.loading:results?.total??0}</p>
     {q&&results&&<p>{results.mode==='hybrid'?t.hybrid:t.lexical}</p>}
     {results?.warnings.some(w=>w==='semantic_index_missing'||w==='semantic_model_unavailable')&&<p>{t.semanticMissing}</p>}
     {results?.warnings.includes('partial_vector_index')&&<p>{t.partialVectors}</p>}
     {results?.warnings.some(w=>w.includes('llm'))&&<p>{t.llmMissing}</p>}
     {results?.interpretation&&<p>{t.rewritten}: <span lang="de">{results.interpretation.query_de}</span></p>}
     {results?.results.length===0&&status?.entries!==0&&<p>{t.empty}</p>}{results?.results.map(card)}
     <p><button disabled={offset.current===0||busy} onClick={()=>void load(q,filters,natural,Math.max(0,offset.current-30))}>{t.previous}</button>{' '}
     <button disabled={!results||offset.current+30>=results.total||busy} onClick={()=>void load(q,filters,natural,offset.current+30)}>{t.next}</button></p>
    </section>
   </>}
   {view==='categories'&&<section>{Object.entries(toc).map(([doc,items])=><section key={doc}><h2>{lang==='es'?'Índice del PDF:':lang==='en'?'PDF outline:':'PDF-Inhaltsverzeichnis:'}</h2><ol>{items.map(([level,title,page],i)=><li key={i}><button onClick={()=>void run(()=>openPage(doc,page))} lang="de">{title} · {t.page} {page} ⭢</button></li>)}</ol></section>)}<h2>{t.categories}:</h2><ul>{categoryList.map(c=><li key={c.typology}><button onClick={()=>{setQ('');searchNow({...blank,typology:c.typology},'');}}>{c.typology} ({c.count}) ⭢</button></li>)}</ul></section>}
   {view==='detail'&&detail&&<article>
    {reference(detail)}<p>{t.labels} {lang==='es'?detail.title_es:lang==='en'?detail.title_en:detail.title_de}</p>
    <p>{[detail.typology,...detail.spaces,...detail.activities,...detail.equipment].join(' · ')}</p>
    <p>{t.confidence}: {Math.round(detail.confidence*100)}% {detail.needs_review>0?`— ${t.reviewNeeded}`:''}</p>
    {detail.needs_review>0&&<button onClick={()=>void run(async()=>{await api('/entries/'+detail.id+'/review',{method:'PATCH',body:JSON.stringify({reviewed:true})});await openDetail(detail.id,false);})}>{t.reviewed}</button>}
    {favoriteButton(detail)}
    <label>{t.add} <select defaultValue="" onChange={e=>{const id=e.target.value;if(id)void run(async()=>{await api(`/collections/${id}/entries/${detail.id}`,{method:'PUT'});await refreshPersonal();});e.target.value='';}}><option value="">—</option>{collections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
    <p><button onClick={()=>void run(()=>openPage(detail.document_id,detail.page_pdf,detail))}>{t.source}</button>{' '}<a href={`/api/documents/${detail.document_id}/source#page=${detail.page_pdf}`} target="_blank" rel="noreferrer">{t.pdf}</a></p>
    <h2>{t.measures}</h2>{detail.dimensions.length?<table><caption>{t.extractive}</caption><thead><tr><th>{t.value}</th><th>{t.unit}</th><th>{t.context}</th></tr></thead><tbody>{detail.dimensions.map((d,i)=><tr key={i}><td>{d.valor}</td><td>{d.unidad}</td><td lang="de">{d.contexto}</td></tr>)}</tbody></table>:<p>{t.none}</p>}
    <h2>{t.figures}</h2>{detail.figures.map((f,i)=><figure key={f.path}><button onClick={()=>setFigure(f.path)} aria-label={`${t.zoom} ${i+1}`}><img src={image(f.path)} width="280" alt={`${t.figure} · ${t.page} ${detail.page_pdf}`}/></button><figcaption>{t.figure}</figcaption></figure>)}
    <h2>{t.text}</h2><p lang="de">{detail.text}</p><button onClick={()=>navigate('library')}>{t.back}</button>
   </article>}
   {view==='viewer'&&viewer&&<section>
    <p>{t.printed}: {viewer.printed||t.unknown}</p>
    <button disabled={viewer.number<=1} onClick={()=>void run(()=>openPage(viewerDoc,viewer.number-1,viewerEntry))}>{t.previous}</button>{' '}
    <button disabled={viewer.number>=viewer.page_count} onClick={()=>void run(()=>openPage(viewerDoc,viewer.number+1,viewerEntry))}>{t.next}</button>
    <form onSubmit={e=>{e.preventDefault();void run(()=>openPage(viewerDoc,Number(pageInput),viewerEntry));}}><label>{t.page} <input type="number" min="1" max={viewer.page_count} required value={pageInput} onChange={e=>setPageInput(e.target.value)}/></label><button>{t.go}</button></form>
    <label>{t.zoom} <input type="range" min="50" max="250" step="10" value={zoom} onChange={e=>setZoom(Number(e.target.value))}/>{zoom}%</label>
    <svg role="img" aria-label={`${t.page} ${viewer.number}`} viewBox={`0 0 ${viewer.width} ${viewer.height}`} width={`${zoom}%`}>
     <image href={image(viewer.image)} width={viewer.width} height={viewer.height}/>
     {viewerEntry&&viewerEntry.page_pdf===viewer.number&&<rect x={viewerEntry.bbox[0]} y={viewerEntry.bbox[1]} width={viewerEntry.bbox[2]-viewerEntry.bbox[0]} height={viewerEntry.bbox[3]-viewerEntry.bbox[1]} fill="#ffff00" fillOpacity="0.2" stroke="currentColor" strokeWidth="2"><title>{viewerEntry.title_de}</title></rect>}
    </svg>
    {viewer.tables_json.map((table,i)=><table key={i}><caption>{t.page} {viewer.number} — {i+1}</caption><tbody>{table.rows.map((row,j)=><tr key={j}>{row.map((cell,k)=><td key={k}>{cell}</td>)}</tr>)}</tbody></table>)}
    {viewerEntry&&<button onClick={()=>void run(()=>openDetail(viewerEntry.id))}>{t.open}</button>}
   </section>}
   {view==='collections'&&<section>
    <form onSubmit={e=>{e.preventDefault();void run(async()=>{await api('/collections',{method:'POST',body:JSON.stringify({name:newName})});setNewName('');await refreshPersonal();});}}><label>{t.newCollection} <input value={newName} maxLength={120} required onChange={e=>setNewName(e.target.value)}/></label><button>{t.create}</button></form>
    {!collections.length&&<p>{t.noCollections}</p>}<ul>{collections.map(c=><li key={c.id}><button onClick={()=>void run(()=>openCollection(c.id))}>{c.name} ({c.count}) ⭢</button></li>)}</ul>
    {collection&&<section><h2>{collection.name}:</h2><p><a href={`/api/collections/${collection.id}/export?format=markdown`} download>{t.exportMd}</a>{' '}<a href={`/api/collections/${collection.id}/export?format=pdf`} download>{t.exportPdf}</a></p>
     <button onClick={()=>{if(confirm(t.confirmDelete))void run(async()=>{await api('/collections/'+collection.id,{method:'DELETE'});setCollection(null);await refreshPersonal();});}}>{t.delete}</button>
     {collection.entries.map(item=><div key={item.id}>{card(item)}<button onClick={()=>void run(async()=>{await api(`/collections/${collection.id}/entries/${item.id}`,{method:'DELETE'});await openCollection(collection.id);await refreshPersonal();})}>{t.remove}</button></div>)}
    </section>}
    <h2>{t.favorites}</h2>{!favorites.length&&<p>{t.noFavorites}</p>}{favorites.map(card)}
   </section>}
   {view==='about'&&<section><p>{t.aboutText}</p><p>{t.local}</p><p>{t.privacy}</p><p>{t.extractive}</p><p>{t.designPending}</p></section>}
  </main>
  <footer><p>neufert · {t.local}</p></footer>
  <dialog ref={dialog} onClose={()=>setFigure('')}><button autoFocus onClick={()=>dialog.current?.close()}>{t.close}</button>{figure&&<p><a href={image(figure)} target="_blank" rel="noreferrer">{t.zoom} ⭢</a></p>}{figure&&<img src={image(figure)} width="600" alt={t.figure}/>}</dialog>
 </>;
}
