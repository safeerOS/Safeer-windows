"""Safeer Media for Linux: local-first media catalogue and MPRIS/playerctl controls.

No cloud account. The catalogue is bounded and scans only standard user media folders.
Playback is delegated to the user's normal Linux applications; MPRIS is used when available.
"""
from __future__ import annotations
import mimetypes, os, subprocess
from pathlib import Path

AUDIO={'.mp3','.flac','.ogg','.oga','.opus','.m4a','.aac','.wav','.wma'}
VIDEO={'.mp4','.mkv','.webm','.avi','.mov','.m4v','.mpeg','.mpg','.ts'}
MAX_FILES=500

def _roots():
    home=Path.home(); out=[]
    for name in ('Music','Glasba','Videos','Video','Movies','Filmi'):
        p=home/name
        if p.is_dir() and p not in out: out.append(p)
    return out

def katalog():
    items=[]
    for root in _roots():
        try:
            for base, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith('.')][:80]
                for f in files:
                    ext=Path(f).suffix.lower()
                    if ext not in AUDIO|VIDEO: continue
                    p=Path(base)/f
                    try: st=p.stat()
                    except OSError: continue
                    items.append({'id':str(p),'naslov':p.stem[:180], 'pot':str(p),
                                  'vrsta':'video' if ext in VIDEO else 'glasba',
                                  'mime':mimetypes.guess_type(str(p))[0] or '', 'cas':int(st.st_mtime)})
                    if len(items)>=MAX_FILES: break
                if len(items)>=MAX_FILES: break
        except OSError: pass
        if len(items)>=MAX_FILES: break
    items.sort(key=lambda x:x['cas'], reverse=True)
    return {'vnosi':items, 'omejeno':len(items)>=MAX_FILES, 'mape':[str(x) for x in _roots()]}

def odpri(pot):
    p=Path(str(pot)).expanduser()
    if not p.is_file() or p.suffix.lower() not in AUDIO|VIDEO: return False
    subprocess.Popen(['xdg-open',str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True

def _playerctl(*args):
    try:
        r=subprocess.run(['playerctl',*args],capture_output=True,text=True,timeout=1.5,check=False)
        return r.stdout.strip() if r.returncode==0 else ''
    except (OSError,subprocess.TimeoutExpired): return ''

def stanje():
    status=_playerctl('status')
    if not status: return {'na_voljo':False}
    fmt='{{title}}\t{{artist}}\t{{position}}\t{{mpris:length}}\t{{xesam:url}}'
    row=_playerctl('metadata','--format',fmt).split('\t')
    while len(row)<5: row.append('')
    def num(v):
        try:return max(0,int(float(v)))
        except:return 0
    return {'na_voljo':True,'predvaja':status.lower()=='playing','naslov':row[0][:200],
            'izvajalec':row[1][:200],'polozaj':num(row[2]),'trajanje':num(row[3])/1_000_000 if num(row[3]) else 0,
            'url':row[4][:2048] if row[4].startswith(('http://','https://')) else ''}

def ukaz(ime):
    cmd={'predvajaj_pavza':'play-pause','naprej':'next','nazaj':'previous','ustavi':'stop'}.get(str(ime))
    if not cmd:return False
    try:return subprocess.run(['playerctl',cmd],timeout=1.5,check=False).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False
