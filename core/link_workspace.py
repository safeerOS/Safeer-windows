"""Safeer Unified Workspace v0.18.
Groups independent continuity activities into portable, passive work contexts.
Receiving a workspace never opens or focuses anything.
"""
import time, uuid
CATEGORY="safeer.workspace.v1"
MAX_WORKSPACES=24
MAX_ACTIVITIES=24
ALLOWED={"workspace_id","title","activity_ids","updated_at","updated_by","archived"}

def sanitize(raw):
    if not isinstance(raw,dict): return {}
    out={k:raw[k] for k in ALLOWED if k in raw and raw[k] is not None}
    wid=str(out.get("workspace_id") or "")[:128]
    if not wid: return {}
    out["workspace_id"]=wid
    out["title"]=str(out.get("title") or "")[:160]
    ids=out.get("activity_ids") if isinstance(out.get("activity_ids"),list) else []
    out["activity_ids"]=list(dict.fromkeys(str(x)[:128] for x in ids if x))[:MAX_ACTIVITIES]
    out["updated_at"]=int(out.get("updated_at") or 0)
    out["archived"]=bool(out.get("archived",False))
    return out

class Workspaces:
    def __init__(self, connection_getter, on_state=None):
        self._connection_getter=connection_getter; self._on_state=on_state; self.version=0; self.items={}; self.current_id=None
    def begin(self,title=""):
        wid="w-"+uuid.uuid4().hex[:24]; self.current_id=wid
        self.upsert({"workspace_id":wid,"title":title,"activity_ids":[]}); return wid
    def attach(self,activity_id,workspace_id=None,title=None):
        wid=workspace_id or self.current_id
        if not wid or not activity_id: return False
        item=dict(self.items.get(wid) or {"workspace_id":wid,"title":title or "","activity_ids":[]})
        if title is not None: item["title"]=title
        item["activity_ids"]=list(dict.fromkeys(list(item.get("activity_ids") or [])+[activity_id]))[-MAX_ACTIVITIES:]
        return self.upsert(item)
    def upsert(self,item):
        clean=sanitize(item)
        if not clean: return False
        clean["updated_at"]=max(int(clean.get("updated_at") or 0),int(time.time()*1000)); wid=clean["workspace_id"]
        old=self.items.get(wid,{})
        if clean["updated_at"]>=int(old.get("updated_at") or 0): self.items[wid]=clean
        self._trim(); self.version=max(self.version+1,int(time.time()*1000))
        c=self._connection_getter(); return bool(c and c.poslji_sync(CATEGORY,self.version,{"items":self.items}))
    def receive(self,payload):
        if payload.get("category")!=CATEGORY: return False
        data=payload.get("data"); incoming=data.get("items") if isinstance(data,dict) and isinstance(data.get("items"),dict) else {}
        changed=False
        for _,raw in incoming.items():
            clean=sanitize(raw)
            if not clean: continue
            wid=clean["workspace_id"]; old=self.items.get(wid,{})
            if int(clean.get("updated_at") or 0)>int(old.get("updated_at") or 0): self.items[wid]=clean; changed=True
        self.version=max(self.version,int(payload.get("version") or 0)); self._trim()
        if changed and self._on_state: self._on_state({"workspaces":dict(self.items),"passive":True})
        return changed
    def activities_for(self,workspace_id): return list((self.items.get(workspace_id) or {}).get("activity_ids") or [])
    def _trim(self):
        if len(self.items)>MAX_WORKSPACES:
            self.items=dict(sorted(self.items.items(),key=lambda kv:int(kv[1].get("updated_at") or 0),reverse=True)[:MAX_WORKSPACES])
