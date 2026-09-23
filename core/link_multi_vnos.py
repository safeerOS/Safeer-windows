"""Safeer Multi-Input Router v0.22.

Zdruzi fizicni gamepad, tipkovnico in misko Linux racunalnika v isto oddaljeno
Android sejo. Nic se ne vklopi samodejno: lastnik UI mora poklicati `vklopi()`.
Modul nikoli ne grabi (/EVIOCGRAB) naprav, zato lokalni Linux ostane uporaben.
"""
from __future__ import annotations
import glob, os, select, struct, threading, time
from typing import Callable, Dict, Optional

EV_KEY, EV_REL, EV_ABS = 0x01, 0x02, 0x03
REL_X, REL_Y, REL_WHEEL = 0, 1, 8
ABS_X, ABS_Y, ABS_RX, ABS_RY, ABS_Z, ABS_RZ, ABS_HAT0X, ABS_HAT0Y = 0,1,3,4,2,5,16,17
# Linux input-event codes; namenoma omejen nabor.
KEYS = {103:"up",108:"down",105:"left",106:"right",28:"enter",1:"back",
        17:"up",31:"down",30:"left",32:"right",57:"enter"}  # W/S/A/D/space
BUTTONS = {304:"a",305:"b",307:"x",308:"y",310:"l1",311:"r1",312:"l2",313:"r2",
           314:"select",315:"start",317:"palica_l",318:"palica_r"}
AXES = {ABS_X:"left_x", ABS_Y:"left_y", ABS_RX:"right_x", ABS_RY:"right_y",
        ABS_Z:"trigger_l", ABS_RZ:"trigger_r", ABS_HAT0X:"dpad_x", ABS_HAT0Y:"dpad_y"}
EVENT = struct.Struct("llHHi")

class MultiInputRouter:
    def __init__(self, send: Callable[[str, dict], bool], device_glob: str="/dev/input/event*"):
        self.send, self.device_glob = send, device_glob
        self.enabled=False; self._stop=threading.Event(); self._thread: Optional[threading.Thread]=None
        self._fds: Dict[int, object]={}; self._pressed=set(); self._last_axis={}

    def vklopi(self) -> bool:
        """Izrecen opt-in uporabnika. Brez tega se ne bere nobene fizicne naprave."""
        if self.enabled: return True
        self._stop.clear(); self.enabled=True
        self._thread=threading.Thread(target=self._run, name="safeer-multi-input", daemon=True); self._thread.start()
        return True

    def izklopi(self) -> None:
        self.enabled=False; self._stop.set(); self.sprosti_vse()
        for f in list(self._fds.values()):
            try: f.close()
            except Exception: pass
        self._fds.clear()

    def sprosti_vse(self) -> None:
        # Android stran je avtoritativna za sprostitev gamepada.
        try: self.send("gamepad.release", {})
        except Exception: pass
        self._pressed.clear(); self._last_axis.clear()

    def feed(self, etype:int, code:int, value:int) -> bool:
        """Prevod enega Linux input dogodka; loceno za testiranje brez /dev/input."""
        if not self.enabled: return False
        if etype == EV_KEY and code in BUTTONS:
            name=BUTTONS[code]; down=value != 0; key=("g",name)
            if value==2: return True
            (self._pressed.add(key) if down else self._pressed.discard(key))
            return bool(self.send("gamepad.button", {"button":name,"down":down}))
        if etype == EV_KEY and code in KEYS:
            # Tipkovnica ostane tipkovnica; Android jo preslika na fokus/touch profil.
            if value==2: return True
            return bool(self.send("input.key", {"key":KEYS[code]})) if value else True
        if etype == EV_ABS and code in AXES:
            # event API ne poda min/max brez ioctl; pogosti gamepadi uporabljajo -32768..32767 ali 0..255.
            if code in (ABS_Z, ABS_RZ): v=max(0.0,min(1.0,value/255.0))
            elif code in (ABS_HAT0X, ABS_HAT0Y): v=max(-1.0,min(1.0,float(value)))
            else: v=max(-1.0,min(1.0,value/32767.0))
            name=AXES[code]
            if abs(v-self._last_axis.get(name,99.0)) < .025: return True
            self._last_axis[name]=v
            return bool(self.send("gamepad.axis", {"axis":name,"value":round(v,4)}))
        if etype == EV_REL:
            if code == REL_WHEEL and value:
                return bool(self.send("input.scroll", {"x":.5,"y":.5,"steps":-max(-8,min(8,value))}))
            # relativna miska se poslje kot majhen swipe/camera dogodek samo, ce se premakne;
            # dejanski kazalec v gledalcu se se naprej obdeluje v WebView UI.
            if code in (REL_X, REL_Y) and value:
                axis="right_x" if code==REL_X else "right_y"
                return bool(self.send("gamepad.axis", {"axis":axis,"value":max(-1.0,min(1.0,value/40.0))}))
        return False

    def _odpri(self):
        for p in glob.glob(self.device_glob):
            try:
                f=open(p,"rb", buffering=0); self._fds[f.fileno()]=f
            except (OSError, PermissionError): pass

    def _run(self):
        self._odpri()
        while self.enabled and not self._stop.is_set():
            if not self._fds:
                self._stop.wait(1.0); self._odpri(); continue
            try: ready,_,_=select.select(list(self._fds),[],[],.25)
            except Exception: continue
            for fd in ready:
                f=self._fds.get(fd)
                try: raw=f.read(EVENT.size)
                except Exception: raw=b""
                if len(raw)!=EVENT.size:
                    try: f.close()
                    except Exception: pass
                    self._fds.pop(fd,None); continue
                _,_,typ,code,val=EVENT.unpack(raw)
                try: self.feed(typ,code,val)
                except Exception: pass
        self.sprosti_vse()
