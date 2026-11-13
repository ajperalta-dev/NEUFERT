'use client';
import {useEffect,useState} from 'react';

type Word=[string,number,number,number,number];
export default function PageWordHighlights({documentId,page,query}:{documentId:string;page:number;query:string}){
  const [words,setWords]=useState<Word[]>([]);
  useEffect(()=>{
    setWords([]);
    if(!query.trim())return;
    const controller=new AbortController();
    const timer=setTimeout(()=>{
      fetch(`/api/pages/${documentId}/${page}/words?q=${encodeURIComponent(query)}`,{signal:controller.signal})
        .then(async r=>{if(!r.ok)throw new Error(String(r.status));return r.json()})
        .then(data=>setWords(data.matches)).catch(()=>{});
    },200);
    return()=>{clearTimeout(timer);controller.abort()};
  },[documentId,page,query]);
  return <div className="page-word-layer" aria-hidden="true">{words.map(([text,x0,y0,x1,y1],i)=><span key={i} title={text} style={{left:`${x0*100}%`,top:`${y0*100}%`,width:`${(x1-x0)*100}%`,height:`${(y1-y0)*100}%`}}/>)}</div>;
}
