"""Manj RAM-a za Safeer OS in Control (lastnik, 11. 10. 2026: »porabo RAM-a zmanjsaj za polovico«).

Meritev (meritve-ram/izhodisce-2026-10-11.txt): proces namizja je po nekaj urah zrasel s 143 na 466 MiB PSS, skoraj vse
anonimni pomnilnik v mnogih areanah glibc (33 niti, vsaka si vzame svojo areno in je ne vrne). Zato:

* omeji_arene(): najvec 2 areni malloc (prej do 8 x st. jeder) - fragmentacija med nitmi izgine.
* obrezuj(): gc + malloc_trim(0) vrne prazne strani sistemu; periodicno, ko program miruje.
* tlak_webkit(): spletni procesi WebKita dobijo mejo pomnilnika - nad njo WebKit sam sprosti predpomnilnike.
"""
import ctypes
import os
import ctypes.util
import gc
import threading

_M_ARENA_MAX = -8
_libc = None


def _c():
    global _libc
    if _libc is None:
        try:
            _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        except OSError:
            _libc = False
    return _libc or None


def _meminfo(kljuc: str) -> int:
    """Vrednost iz /proc/meminfo v bajtih ali -1."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as d:
            for v in d:
                if v.startswith(kljuc + ":"):
                    return int(v.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return -1


def _stanje_windows():
    """MEMORYSTATUSEX ali None (samo Windows)."""
    try:
        class _Stanje(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stanje = _Stanje()
        stanje.dwLength = ctypes.sizeof(stanje)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stanje)):  # type: ignore[attr-defined]
            return stanje
    except Exception:  # noqa: BLE001
        pass
    return None


def na_voljo() -> int:
    """Pomnilnik, ki ga sistem lahko da brez izrinjanja (Linux MemAvailable, Windows ullAvailPhys), v bajtih; -1,
    ce ga sistem ne pove. Merjeno sproti - na tem odlocajo meje za clane kroga Safeer Linka (core/link_viri.py)."""
    if os.name == "nt":
        s = _stanje_windows()
        return int(s.ullAvailPhys) if s is not None else -1
    return _meminfo("MemAvailable")


def skupaj() -> int:
    """Ves fizicni pomnilnik v bajtih ali -1."""
    if os.name == "nt":
        s = _stanje_windows()
        return int(s.ullTotalPhys) if s is not None else -1
    return _meminfo("MemTotal")


def omeji_arene(st: int = 2) -> bool:
    """Klici cim prej (pred nitmi). Brez glibc (drug sistem) ne naredi nic."""
    c = _c()
    if c is None or not hasattr(c, "mallopt"):
        return False
    try:
        return bool(c.mallopt(_M_ARENA_MAX, int(st)))
    except Exception:  # noqa: BLE001
        return False


def obrezuj() -> bool:
    # gc samo na glavni niti (18. 10. 2026): finalize predmeta WebKit/GTK zunaj nje sesuje proces (signal 5).
    if threading.current_thread() is threading.main_thread():
        gc.collect()  # glavna nit
    c = _c()
    if c is None or not hasattr(c, "malloc_trim"):
        return False
    try:
        return bool(c.malloc_trim(0))
    except Exception:  # noqa: BLE001
        return False


#: Periodicno obrezovanje samo, ce je anonimni RSS od zadnjega obrezovanja zrasel vsaj za toliko (KiB).
PRAG_OBREZOVANJA_KIB = 4096
#: anon: RSS po zadnjem obrezovanju; po_rasti: zadnje obrezovanje je bilo zaradi rasti (delo morda se tece).
_po_obrezovanju = {"anon": -1, "po_rasti": False}


def _anon_kib() -> int:
    """Anonimni (zasebni) rezidencni pomnilnik tega procesa v KiB iz /proc/self/statm (resident - shared); -1 drugje."""
    try:
        with open("/proc/self/statm", encoding="ascii") as d:
            v = d.read().split()
        return (int(v[1]) - int(v[2])) * (os.sysconf("SC_PAGE_SIZE") // 1024)
    except (OSError, ValueError, IndexError):
        return -1


def obrezuj_ce_treba(prag_kib: int = PRAG_OBREZOVANJA_KIB) -> bool:
    """Periodicno obrezovanje: gc + malloc_trim samo, ce je proces od zadnjega obrezovanja zrasel za prag_kib. Do
    19. 10. 2026 je periodicno obrezovanje teklo vsakih 90 s tudi v mirovanju (meritev v vsebniku: do 21 ms glavne niti
    Safeer OS na klic - polno zbiranje in malloc_trim -, ko ni bilo nic vrniti). Po obrezovanju zaradi rasti obrezuje se
    enkrat: kar je delo sprostilo po tem (zaprt zavihek, konec nalaganja), RSS ne poveca, a malloc to drzi do obrezovanja.
    Vrne, ali je obrezoval."""
    anon = _anon_kib()
    prej = _po_obrezovanju["anon"]
    zrasel = anon < 0 or prej < 0 or anon - prej >= prag_kib
    if not zrasel and not _po_obrezovanju["po_rasti"]:
        return False
    obrezuj()
    _po_obrezovanju["anon"] = _anon_kib()
    _po_obrezovanju["po_rasti"] = zrasel
    return True


def obrezuj_periodicno(GLib, sekunde: int = 90) -> None:
    """Na glavni niti, vsakih `sekunde`: obrezovanje (nekaj ms), ce je bilo od zadnjega kaj dela (obrezuj_ce_treba)."""
    def korak():
        obrezuj_ce_treba()
        return True
    GLib.timeout_add_seconds(int(sekunde), korak)


def meja_strani_mb(skupaj_mb: int = 0) -> int:
    """Koliko pomnilnika sme porabiti en proces strani, preden ga WebKit ustavi: polovica RAM-a, najmanj 1,5 GB,
    najvec 8 GB. Meritev 13. 10. 2026 (testni racunalnik, 12 GB): en proces strani je zrasel na ~7 GB in sistem
    je moral ubijati programe (OOM); brez meje ena pozresna stran ustavi ves racunalnik. Prej cetrtina (najvec 4 GB):
    JetStream 3.0 potrebuje do 2,7 GB (meritev 17. 10. 2026) in ga je varuh ustavil - odlocitev lastnika 17. 10. 2026:
    polovica RAM-a."""
    if skupaj_mb <= 0:
        try:
            skupaj_mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
        except (ValueError, OSError, AttributeError):
            skupaj_mb = 8192
    return int(min(8192, max(1536, skupaj_mb // 2)))


def meja_sprostitve_mb(skupaj_mb: int = 0) -> int:
    """Meja, nad katero WebKit procesu strani sprosti predpomnilnike (njena tretjina, "conservative") - polovica meje
    ubijanja. Prej 350 MB: WebKit je predpomnilnike praznil ze pri ~115 MB, torej pri skoraj vsaki strani; meritev
    13. 10. 2026 (testni PC, 8 strani, isti proces izmenicno): toplo LCP Splet 752 ms proti 388 ms golega WebKita,
    z mejo 1500 MB 400 ms."""
    return meja_strani_mb(skupaj_mb) // 2


def tlak_webkit(WebKit2, meja_mb: int, ubij_mb: int = 0):
    """MemoryPressureSettings za WebContext (WebKitGTK 2.34+) ali None. ubij_mb > meja_mb: nad to porabo WebKit
    proces strani ustavi (Splet ga potem nalozi znova ali pokaze razlago - os_splet._proces_koncan)."""
    try:
        s = WebKit2.MemoryPressureSettings.new()
        s.set_memory_limit(int(meja_mb))
        if ubij_mb > meja_mb:
            s.set_kill_threshold(float(ubij_mb) / float(meja_mb))
            s.set_poll_interval(5.0)    # privzeto 30 s: pozresna stran bi medtem pobrala se gigabajte (preizkus: 1,6 GB/s)
        return s
    except Exception:  # noqa: BLE001
        return None


def kontekst(WebKit2, meja_mb: int, ubij_mb: int = 0, **lastnosti):
    """Nov WebContext z mejo pomnilnika za spletne procese; brez podpore navaden WebContext."""
    s = tlak_webkit(WebKit2, meja_mb, ubij_mb)
    if s is not None:
        try:
            return WebKit2.WebContext(memory_pressure_settings=s, **lastnosti)
        except Exception:  # noqa: BLE001
            pass
    return WebKit2.WebContext(**lastnosti)


def tlak_omrezja(WebKit2, meja_mb: int) -> bool:
    """Meja pomnilnika za omrezne procese WebKita (WebKitGTK 2.34+, velja za vse, ustvarjene po klicu).

    Stresni preizkus na lastnikovem racunalniku 12. 10. 2026: omrezni proces Spleta je v 15 minutah iskanja zrasel s
    187 na 278 MiB (vse anonimni pomnilnik), en zavihek, eno okno. Nad mejo WebKit omreznemu procesu sprosti
    predpomnilnike. Klicati pred prvim pogledom WebKit v procesu."""
    s = tlak_webkit(WebKit2, meja_mb)
    if s is None:
        return False
    # WebKitGTK 6.0 (GTK4): staticna metoda je na NetworkSession; 4.1: na WebsiteDataManager.
    for razred in ("NetworkSession", "WebsiteDataManager"):
        try:
            getattr(WebKit2, razred).set_memory_pressure_settings(s)
            return True
        except Exception:  # noqa: BLE001 - starejsi WebKitGTK ali drug API
            continue
    return False


def recikliraj_omrezni(*, okno_aktivno: bool, neaktivno_s: float, prenosi: bool, nalaganje: bool,
                       zvok: bool, pss_mb: float, meja_mb: float, mirovanje_s: float = 300.0) -> bool:
    """Ali Safeer Browser sme koncati svoj omrezni proces (WebKit takoj zazene novega). Klice ga samo recikliranje v
    splet_spanje, ki je v 1.0.129 izklopljeno (RECIKLIRANJE_OMREZNEGA).

    12. 10. 2026: libsoup 3.4.4-5ubuntu0.9 pri vsaki povezavi prek posrednika (nas DoH) pusti SoupConnection, zato
    omrezni proces raste. Uporabniku to ne sme nicesar pokvariti: nikoli med uporabo okna, prenosom, nalaganjem ali
    predvajanjem zvoka, in samo nad visoko mejo (ob koncu se izgubijo piskotki seje, trajni ostanejo)."""
    if meja_mb <= 0 or okno_aktivno or prenosi or nalaganje or zvok:
        return False
    return neaktivno_s >= mirovanje_s and pss_mb >= meja_mb
