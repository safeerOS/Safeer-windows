"""Safeer Media Sync v1.1: per-item merge with tombstones.
Portable metadata only; local paths, credentials and network permissions never sync.
"""
import time
CATEGORY="safeer.media.v1"; MAX_SOURCES,MAX_FAVORITES,MAX_PROGRESS=80,300,30; TOMBSTONE_MS=30*24*3600*1000

def _http(v):
 s=str(v or '').strip(); return s if s.startswith(('https://','http://')) else ''
def _ts(x,fallback):
 try:return max(0,int(x.get('updated') or fallback or 0))
 except:return int(fallback or 0)
def _clean(data, keep_deleted=True):
 data=data if isinstance(data,dict) else {}; base=int(data.get('updated') or time.time()*1000); out={}
 specs=(('sources',MAX_SOURCES,lambda x:_http(x.get('url'))),('favorites',MAX_FAVORITES,lambda x:str(x.get('id') or '')[:300]),('progress',MAX_PROGRESS,lambda x:str(x.get('id') or '')[:300]))
 for name,limit,keyfn in specs:
  rows=[]
  for x in (data.get(name) or []):
   if not isinstance(x,dict):continue
   key=keyfn(x)
   if not key:continue
   deleted=bool(x.get('deleted')); updated=_ts(x,base)
   if deleted:
    if keep_deleted: rows.append({'id':key,'updated':updated,'deleted':True} if name!='sources' else {'url':key,'updated':updated,'deleted':True})
    continue
   if name=='sources': rows.append({'type':str(x.get('type') or '')[:24],'name':str(x.get('name') or '')[:120],'url':key[:2048],'updated':updated})
   elif name=='favorites':
    url=_http(x.get('url'))
    if url: rows.append({'id':key,'title':str(x.get('title') or '')[:200],'artist':str(x.get('artist') or '')[:160],'url':url[:2048],'video':bool(x.get('video')),'updated':updated})
   else:
    try:pos=max(0.,float(x.get('position') or 0));dur=max(0.,float(x.get('duration') or 0))
    except (TypeError,ValueError):continue
    if dur>0 and pos<dur*.95: rows.append({'id':key,'title':str(x.get('title') or '')[:200],'position':pos,'duration':dur,'updated':updated})
    elif keep_deleted: rows.append({'id':key,'updated':updated,'deleted':True})
  rows.sort(key=lambda x:x.get('updated',0),reverse=True); out[name]=rows[:limit]
 out['updated']=base; return out

def merge(a,b,now_ms=None):
 now=int(now_ms or time.time()*1000); aa=_clean(a); bb=_clean(b); result={}
 for name,limit,key in [('sources',MAX_SOURCES,'url'),('favorites',MAX_FAVORITES,'id'),('progress',MAX_PROGRESS,'id')]:
  m={}
  for x in aa[name]+bb[name]:
   k=x.get(key)
   if k and (k not in m or x.get('updated',0)>m[k].get('updated',0)):m[k]=x
  rows=[x for x in m.values() if not (x.get('deleted') and now-x.get('updated',0)>TOMBSTONE_MS)]
  rows.sort(key=lambda x:x.get('updated',0),reverse=True); result[name]=rows[:limit]
 result['updated']=max(int(aa.get('updated',0)),int(bb.get('updated',0)),now); return result

def sanitize(data):
 c=_clean(data,False); return c

class MediaSync:
 def __init__(self,connection_getter,on_state=None):self._connection_getter=connection_getter;self._on_state=on_state;self.version=0;self._state=_clean({})
 @property
 def state(self):return sanitize(self._state)
 def request_latest(self):
  c=self._connection_getter();return bool(c and c.zahtevaj_sync(CATEGORY,self.version))
 def publish(self,state):
  now=int(time.time()*1000); self._state=merge(self._state,state,now); self.version=max(self.version+1,now)
  c=self._connection_getter();return bool(c and c.poslji_sync(CATEGORY,self.version,self._state))
 def receive(self,payload):
  if payload.get('category')!=CATEGORY:return False
  data=payload.get('data');
  if not isinstance(data,dict):return False
  incoming=_clean(data); before=self._state; self._state=merge(self._state,incoming); self.version=max(self.version,int(payload.get('version') or 0))
  changed=self._state!=before
  if changed and self._on_state:self._on_state(self.state)
  return changed
