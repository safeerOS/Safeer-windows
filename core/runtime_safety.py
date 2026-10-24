"""Keep cyclic Python/GObject finalization on GTK's owning thread.

Samodejni gc je izklopljen (v delovni niti bi sprostil predmet WebKit/GTK - SIGTRAP), smeti pobira glavna zanka. Do
19. 10. 2026 je to naredila vsaki 2 s (generacija 0) in vsakih 30 s polno (generacija 2) - ne glede na to, ali je bilo
kaj novega. Meritev v mirovanju (vsebnik, Xvfb, delovna povrsina z lupino v svojem procesu, 120 s): 60 klicev, 66 ms
glavne niti, polno zbiranje do 17,7 ms (zastoj zanke, cel izrisani okvir). Zdaj velja isto pravilo kot za samodejni gc
Pythona (pragovi gc.get_threshold po stevcih gc.get_count): kadar ni novih predmetov, ni dela; polno zbiranje po pragu
najvec vsakih POLNO_NAJMANJ_S in po delu najkasneje po POLNO_NAJVEC_S (smeti iz starejse generacije ne cakajo ur).
"""
import gc
import threading
import time

from gi.repository import GLib

_gc_source = None
#: Kako pogosto glavna zanka preveri stevce gc (s). Isti takt kot utrip varuha (core/varuh_procesov.UTRIP_S):
#: timeout_add_seconds ju zdruzi v eno bujenje.
TIK_S = 5
#: Polno zbiranje (generacija 2) po pragu najvec tako pogosto - samodejni gc ga dodatno omeji z rastjo starih predmetov
#: (25 %), cesar Python ne izpostavi.
POLNO_NAJMANJ_S = 120.0
#: Ce je bilo od zadnjega polnega zbiranja kaj dela (zbrana mlajsa generacija), polno zbiranje najkasneje po tem casu.
POLNO_NAJVEC_S = 600.0

_stanje = {"polno": 0.0}


def korak(ura=time.monotonic) -> int:
    """En pregled stevcev: zbere generacijo, ki je presegla prag, ali nic. Vrne zbrano generacijo ali -1."""
    c0, c1, c2 = gc.get_count()
    t0, t1, t2 = gc.get_threshold()
    zdaj = ura()
    od_polnega = zdaj - _stanje["polno"]
    if (c2 > t2 and od_polnega >= POLNO_NAJMANJ_S) or ((c1 or c2) and od_polnega >= POLNO_NAJVEC_S):
        generacija = 2
    elif c1 > t1:
        generacija = 1
    elif c0 > t0:
        generacija = 0
    else:
        return -1
    gc.collect(generacija)
    if generacija == 2:
        _stanje["polno"] = zdaj
    return generacija


def install_main_thread_gc():
    """Automatic GC may run in a DNS worker and finalize a WebKit wrapper there."""
    global _gc_source
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('GTK must be initialized on the main thread')
    if _gc_source is not None:
        return
    gc.disable()
    _stanje["polno"] = time.monotonic()

    def collect():
        korak()
        return GLib.SOURCE_CONTINUE
    _gc_source = GLib.timeout_add_seconds(TIK_S, collect)


def collect_closed_views():
    """Called through the GTK loop after a tab has been detached and destroyed."""
    gc.collect()
    _stanje["polno"] = time.monotonic()
    return GLib.SOURCE_REMOVE
