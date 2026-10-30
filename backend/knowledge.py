"""Small, transparent lexical retrieval over a locally curated JSON corpus.

This is deliberately not described as a live web search. Add only reviewed source excerpts
with their original title, URL, date, and text to knowledge_base.json.
"""
import json
import re
from pathlib import Path

CORPUS_PATH = Path(__file__).resolve().parent / "knowledge_base.json"

def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower()) if len(t) > 2}

def load_documents() -> list[dict]:
    try:
        payload=json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        docs=payload.get("documents", [])
        return [d for d in docs if isinstance(d,dict) and d.get("text") and d.get("title") and d.get("url")]
    except (OSError, ValueError, AttributeError):
        return []

def retrieve(query: str, limit: int=3) -> list[dict]:
    query_tokens=_tokens(query)
    if not query_tokens: return []
    scored=[]
    for doc in load_documents():
        doc_tokens=_tokens(f"{doc.get('title','')} {doc.get('text','')}")
        overlap=query_tokens & doc_tokens
        if overlap:
            scored.append((len(overlap)/max(len(query_tokens),1),doc))
    scored.sort(key=lambda item:item[0],reverse=True)
    results=[]
    for score,doc in scored[:max(1,min(limit,5))]:
        if score <= 0: continue
        results.append({"title":doc["title"],"url":doc["url"],"date":doc.get("date"),"text":doc["text"][:5000],"score":round(score,3)})
    return results


def _norm_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(label).lower()).strip()

def retrieve_for_labels(labels: list[str], limit: int=3) -> list[dict]:
    """Return reviewed excerpts for classifier labels.

    Documents may carry an optional ``labels`` list (exact classifier class names). Exact label
    matches come first, in the order the labels were given (most likely first). If no document
    declares a matching label, fall back to the same lexical matching used by /ask.
    """
    wanted=[_norm_label(l) for l in labels if l]
    if not wanted: return []
    results=[]
    seen=set()
    for rank,want in enumerate(wanted):
        for doc in load_documents():
            declared={_norm_label(x) for x in doc.get("labels",[]) if isinstance(x,str)}
            if want in declared and doc["url"] not in seen:
                seen.add(doc["url"])
                results.append({"title":doc["title"],"url":doc["url"],"date":doc.get("date"),"text":doc["text"][:5000],"score":1.0,"matched_by":"label","rank":rank})
    if results:
        return results[:max(1,min(limit,5))]
    # Keyword fallback is deliberately strict: a crop name alone (e.g. "maize") must not pull in
    # an unrelated document, so most of the label's words have to appear in the excerpt.
    query_tokens=_tokens(wanted[0])
    scored=[]
    for doc in load_documents():
        overlap=query_tokens & _tokens(f"{doc.get('title','')} {doc.get('text','')}")
        if len(overlap)>=2 and len(overlap)/max(len(query_tokens),1)>=0.6:
            scored.append((len(overlap)/len(query_tokens),doc))
    scored.sort(key=lambda item:item[0],reverse=True)
    return [{"title":d["title"],"url":d["url"],"date":d.get("date"),"text":d["text"][:5000],"score":round(sc,3),"matched_by":"text"} for sc,d in scored[:max(1,min(limit,5))]]
