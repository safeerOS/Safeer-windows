"""Universal Handoff v1 over the existing authenticated Safeer Link connection."""
import time, uuid
TYPE="handoff.request"; MAX_URL=2048

def clean_payload(data):
 d=data if isinstance(data,dict) else {}; url=str(d.get('url') or '')[:MAX_URL]
 if not url.startswith(('http://','https://')): return None
 try:pos=max(0.0,float(d.get('position') or 0))
 except (TypeError,ValueError):pos=0.0
 return {'surface':str(d.get('surface') or 'media')[:32],'url':url,'title':str(d.get('title') or '')[:200],'position':pos,'media_id':str(d.get('media_id') or '')[:300],'created':int(time.time()*1000)}

def message(target,data):
 p=clean_payload(data)
 if not target or not p:return None
 return {'id':str(uuid.uuid4()),'type':TYPE,'target':str(target),'payload':p}
