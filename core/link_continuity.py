"""Safeer Continuity v3 -- en delovni prostor, vec hkratnih naprav.

Oddaljeno stanje je vedno pasivno. Zapis je per-activity, ne per-device. Lokalni UI ga
uporabi samo, ko uporabnik odpre isti vir/aktivnost. To omogoca hkratno delo na TV,
telefonu, tablici in Linuxu brez oddaljenih preklopov.
"""
import time, hashlib
CATEGORY = "safeer.continuity.v3"
OLD = {"safeer.continuity.v2", "safeer.continuity.v1"}
MAX_ITEMS = 160
ALLOWED = {
    "activity_id","kind","surface","resource_id","url","title","query",
    "media_id","media_title","media_position","media_duration","media_playing",
    "file_id","file_name","file_position","app_id","app_title","app_context",
    "cursor","scroll","selection","workspace_id","updated_by","updated_at"
}

def sanitize(state):
    out={k:state[k] for k in ALLOWED if k in state and state[k] is not None}
    if "url" in out and not str(out["url"]).startswith(("http://","https://")): out.pop("url",None)
    # Never synchronize local paths, credentials, network coordinates or session secrets.
    for k in tuple(out):
        if any(x in k.lower() for x in ("token","secret","password","cookie","cert","fingerprint","local_path","ip_address")):
            out.pop(k,None)
    return out

def resource_key(state):
    s=sanitize(state); kind=str(s.get("kind") or s.get("surface") or "unknown")
    ident=str(s.get("resource_id") or s.get("media_id") or s.get("file_id") or s.get("app_id") or s.get("url") or s.get("query") or s.get("title") or "")
    return (kind+"|"+ident)[:2300] if ident else ""

def activity_id_for(state):
    s=sanitize(state)
    if s.get("activity_id"): return str(s["activity_id"])[:128]
    key=resource_key(s)
    return ("a-"+hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]) if key else ""

class Continuity:
    def __init__(self, connection_getter, on_state=None):
        self._connection_getter=connection_getter; self._on_state=on_state; self.version=0; self.items={}
    @property
    def state(self):
        return max(self.items.values(), key=lambda x:int(x.get("updated_at") or 0), default={})
    def request_latest(self):
        c=self._connection_getter(); return bool(c and c.zahtevaj_sync(CATEGORY,self.version))
    def publish(self,state):
        clean=sanitize(state); aid=activity_id_for(clean)
        if not aid: return False
        clean["activity_id"]=aid; clean["updated_at"]=max(int(clean.get("updated_at") or 0),int(time.time()*1000))
        old=self.items.get(aid,{})
        if int(clean["updated_at"]) >= int(old.get("updated_at") or 0): self.items[aid]=clean
        self._trim(); self.version=max(self.version+1,int(time.time()*1000))
        c=self._connection_getter(); return bool(c and c.poslji_sync(CATEGORY,self.version,{"items":self.items}))
    def publish_browser(self,url,title="",**extra): return self.publish(dict(extra,kind="browser",surface="browser",url=url,title=title,resource_id=url))
    def publish_search(self,query,**extra): return self.publish(dict(extra,kind="search",surface="search",query=query,resource_id=query))
    def publish_file(self,file_id,file_name="",**extra): return self.publish(dict(extra,kind="file",surface="files",file_id=file_id,file_name=file_name,resource_id=file_id))
    def publish_remote_app(self,app_id,app_title="",**extra): return self.publish(dict(extra,kind="remote_app",surface="remote_app",app_id=app_id,app_title=app_title,resource_id=app_id))
    def receive(self,payload):
        if payload.get("category") not in ({CATEGORY}|OLD): return False
        version=int(payload.get("version") or 0); data=payload.get("data")
        if not isinstance(data,dict): return False
        incoming=data.get("items") if isinstance(data.get("items"),dict) else {activity_id_for(data):data}
        changed=False
        for _,raw in incoming.items():
            if not isinstance(raw,dict): continue
            clean=sanitize(raw); aid=activity_id_for(clean)
            if not aid: continue
            clean["activity_id"]=aid; old=self.items.get(aid,{})
            if int(clean.get("updated_at") or version)>int(old.get("updated_at") or 0):
                clean["updated_at"]=int(clean.get("updated_at") or version); self.items[aid]=clean; changed=True
        self.version=max(self.version,version); self._trim()
        if changed and self._on_state: self._on_state({"items":dict(self.items),"passive":True})
        return changed
    def resume_for(self,state):
        aid=activity_id_for(state)
        if aid and aid in self.items: return dict(self.items[aid])
        key=resource_key(state)
        matches=[x for x in self.items.values() if resource_key(x)==key]
        return dict(max(matches,key=lambda x:int(x.get("updated_at") or 0),default={}))
    def activities(self,kind=None):
        vals=list(self.items.values())
        if kind: vals=[x for x in vals if x.get("kind")==kind]
        return sorted((dict(x) for x in vals),key=lambda x:int(x.get("updated_at") or 0),reverse=True)
    def _trim(self):
        if len(self.items)>MAX_ITEMS:
            self.items=dict(sorted(self.items.items(),key=lambda kv:int(kv[1].get("updated_at") or 0),reverse=True)[:MAX_ITEMS])
