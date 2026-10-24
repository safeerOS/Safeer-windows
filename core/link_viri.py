"""Viri stroja za clane kroga Safeer Linka: koliko clanov sprejmemo, odlocajo samo pravi viri, merjeni sproti.

Lastnik, 18. 10. 2026: »Zakaj moramo imeti omejitve glede kroga zaupanja in pri neposrednih vhodih od zunaj? Kaj ce
bi nase okolje zelelo imeti veliko podjetje, kot je BSH?« Clan kroga (dokazan s podpisom kljuca naprave) zato nima vec
fiksne stevilke (32 naprav na sredisce, 64 tunelov, 32 sej Teamworka na napravo ...). Novo povezavo ali delo za clana
zavrnemo samo, ko racunalniku res zmanjkuje deskriptorjev, pomnilnika ali niti - in takrat z jasnim razlogom (koda
`ni_virov`, besedilo v sestih jezikih, obvestilo na tej napravi), nikoli tiho.

Fiksne meje ostanejo samo za NEPREVERJENE (kdor se se ni podpisal s kljucem iz kroga) in kot tehnicne meje protokola
(velikost okvirja, dolzina imena) - pregled v docs/LINK-MESH.md, »Meje in roki, ki jih uporabnik lahko obcuti«.

Rezerve (zakaj prav toliko):
  * deskriptorji: Safeer OS tece v enem procesu (namizje, Control, Link, Splet). 16. in 17. 10. 2026 je pri meji 1024
    koncal s SIGTRAP, ker WebKit ni dobil deskriptorja za memfd novega spletnega procesa (core/os_stabilnost.py). Ob
    zagonu ima proces ~150 deskriptorjev, straza opozori pri 400 (os_deskriptorji.PRAG_OPOZORILA). Link zato pusti
    ostalemu procesu vedno vsaj REZERVA_DESKRIPTORJEV prostih (pri nizki meji cetrtino meje);
  * pomnilnik: Splet uspava zavihke pod 10 % MemAvailable (core/splet_spanje.py); Link sprejema clane dlje, a ustavi
    nove pri 5 % (najmanj 256 MiB), da sistem ne pride do ubijalca OOM;
  * disk: rezerva je delez diska (2 %, najmanj 1 GiB, najvec 10 GiB), ne ena stevilka za vse diske.
"""
from __future__ import annotations

import errno
import os
import shutil
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from core import pomnilnik

#: Prostih deskriptorjev, ki jih Link vedno pusti ostalemu procesu (GLib, WebKit, datoteke); pri meji pod 2048
#: cetrtina meje.
REZERVA_DESKRIPTORJEV = 512
#: Pomnilnik, pod katerim Link ne sprejme novega clana: delez vsega RAM-a, a najmanj toliko bajtov.
DELEZ_POMNILNIKA = 0.05
REZERVA_POMNILNIKA_B = 256 * 1024 * 1024
#: Rezerva diska: delez zmogljivosti, najmanj in najvec (glej rezerva_diska).
DELEZ_DISKA = 0.02
NAJMANJ_REZERVE_DISKA = 1024 ** 3
NAJVEC_REZERVE_DISKA = 10 * 1024 ** 3

#: Razlogi zavrnitve (koda za vmesnik in dnevnik).
DESKRIPTORJI = "deskriptorji"
POMNILNIK = "pomnilnik"
NITI = "niti"
#: Koda napake v odgovorih Linka, kadar clan ni sprejet zaradi virov (napravi, ki prosi).
KODA = "ni_virov"

#: Stanje pomanjkanja se v vmesniku kaze toliko casa po zadnji zavrnitvi.
VELJA_S = 600.0
#: Obvestilo namizja o pomanjkanju najvec tako pogosto (dnevnik najvec enkrat na DNEVNIK_VSAKIH_S).
OBVESTILO_VSAKIH_S = 600.0
DNEVNIK_VSAKIH_S = 60.0


# ------------------------------------------------------------------ meritve (vsak klic sproti)

def meja_deskriptorjev() -> int:
    """Mehka meja odprtih deskriptorjev procesa (RLIMIT_NOFILE) ali -1 (neznana ali brez meje, npr. Windows)."""
    try:
        import resource
        mehka, _trda = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ImportError, ValueError, OSError):
        return -1
    if mehka == getattr(resource, "RLIM_INFINITY", -1) or mehka <= 0:
        return -1
    return int(mehka)


def rezerva_deskriptorjev(meja: int) -> int:
    return min(REZERVA_DESKRIPTORJEV, max(0, meja) // 4)


#: Stetje /proc/self/fd stane (izmerjeno 18. 10. 2026: 6,8 ms pri 10 000 odprtih). Dalec od meje (vec kot toliko
#: prostih nad rezervo) velja meritev najvec SVEZE_S - val tisoc novih clanov tako ne porabi sekund procesorja za
#: stetje; blizu meje se steje ob vsakem vprasanju (natancno).
PROSTIH_ZA_PREDPOMNILNIK = 2048
SVEZE_S = 1.0
_zadnja_meritev: List[float] = [-1e18, 0.0]       # (kdaj, prostih)


def prostih_deskriptorjev() -> Optional[int]:
    """Koliko deskriptorjev ima Link se na voljo nad rezervo za ostali proces (lahko negativno); None = ne vemo
    (ni /proc ali ni meje - Windows). Ce za stetje ni vec niti enega deskriptorja (EMFILE), je odgovor »nic«.

    Stetje /proc/self/fd ne vidi stevilk, ki jih jedro rezervira nitim v accept() (Linux dodeli stevilko nove
    povezave, preden caka nanjo) - zato rezerva, ne natancna meja."""
    zdaj = time.monotonic()
    kdaj, prostih = _zadnja_meritev
    if zdaj - kdaj < SVEZE_S and prostih > PROSTIH_ZA_PREDPOMNILNIK:
        return int(prostih)
    meja = meja_deskriptorjev()
    try:
        odprtih = len(os.listdir("/proc/self/fd"))
    except OSError as e:
        if getattr(e, "errno", None) in (errno.EMFILE, errno.ENFILE):
            return -rezerva_deskriptorjev(meja) if meja > 0 else 0
        return None
    if meja < 0:
        return None
    prostih = meja - rezerva_deskriptorjev(meja) - odprtih
    _zadnja_meritev[:] = [zdaj, float(prostih)]
    return prostih


def rezerva_pomnilnika(skupaj_b: int) -> int:
    return max(REZERVA_POMNILNIKA_B, int(max(0, skupaj_b) * DELEZ_POMNILNIKA))


def prostega_pomnilnika() -> Optional[int]:
    """Pomnilnik nad rezervo v bajtih (lahko negativno); None = sistem ne pove."""
    na_voljo = pomnilnik.na_voljo()
    if na_voljo < 0:
        return None
    return na_voljo - rezerva_pomnilnika(pomnilnik.skupaj())


def preveri(deskriptorjev: int = 1, pomnilnika: int = 0) -> str:
    """"" = racunalnik zmore se toliko deskriptorjev in bajtov pomnilnika nad rezervama; sicer razlog (DESKRIPTORJI,
    POMNILNIK). Brez podatka (drug sistem) sprejmemo: tam ne vemo vec od sistema, ki sam zavrne, kar ne gre."""
    prosti = prostih_deskriptorjev()
    if prosti is not None and prosti < deskriptorjev:
        return DESKRIPTORJI
    prostega = prostega_pomnilnika()
    if prostega is not None and prostega < max(0, pomnilnika):
        return POMNILNIK
    return ""


def rezerva_diska(mapa: str) -> int:
    """Koliko prostora na disku z `mapa` mora ostati prostega po nasem pisanju: 2 % diska, najmanj 1 GiB, najvec
    10 GiB (prej ena stevilka 1 GiB za vse: na disku 64 GB je to 1,6 %, na 2 TB 0,05 %)."""
    try:
        skupaj = shutil.disk_usage(mapa).total
    except OSError:
        return NAJMANJ_REZERVE_DISKA
    return int(min(NAJVEC_REZERVE_DISKA, max(NAJMANJ_REZERVE_DISKA, skupaj * DELEZ_DISKA)))


def zazeni_nit(cilj: Callable[..., None], args: tuple = (), ime: str = "safeer-link", kje: str = "") -> bool:
    """Nit za clana. Ce je sistem ne da (RuntimeError: meja niti ali pomnilnika), to zabelezi kot pomanjkanje."""
    try:
        threading.Thread(target=cilj, args=args, name=ime, daemon=True).start()
        return True
    except RuntimeError:
        zabelezi(NITI, kje)
        return False


# ------------------------------------------------------------------ pomanjkanje: dnevnik, vmesnik, obvestilo

_zaklep = threading.Lock()
_stanje: Dict[str, object] = {"razlog": "", "kje": "", "ob": 0.0, "zavrnjenih": 0}
_zadnje_obvestilo = -1e18
_zadnji_dnevnik = -1e18
#: Klici ob pomanjkanju (razlog, kje, stevilo zavrnjenih) - najvec enkrat na OBVESTILO_VSAKIH_S. Sredisce
#: (core/link_hub_streznik.py) tu prijavi obvestilo namizja.
POSLUSALCI: List[Callable[[str, str, int], None]] = []


def zabelezi(razlog: str, kje: str = "") -> None:
    """Clan ni bil sprejet zaradi virov: v dnevnik, v stanje za vmesnik in (redko) obvestilo uporabniku."""
    global _zadnje_obvestilo, _zadnji_dnevnik
    zdaj = time.monotonic()
    with _zaklep:
        if zdaj - float(_stanje["ob"] or 0.0) > VELJA_S:
            _stanje["zavrnjenih"] = 0
        _stanje.update(razlog=razlog, kje=kje, ob=zdaj, zavrnjenih=int(_stanje["zavrnjenih"] or 0) + 1)
        n = int(_stanje["zavrnjenih"])
        dnevnik = zdaj - _zadnji_dnevnik >= DNEVNIK_VSAKIH_S
        if dnevnik:
            _zadnji_dnevnik = zdaj
        obvesti = zdaj - _zadnje_obvestilo >= OBVESTILO_VSAKIH_S
        if obvesti:
            _zadnje_obvestilo = zdaj
        poslusalci = list(POSLUSALCI) if obvesti else []
    if dnevnik:
        prosti, prostega = prostih_deskriptorjev(), prostega_pomnilnika()
        print("[SafeerLink] viri: clan ni sprejet (%s, %s) - zavrnjenih v zadnjih %d min: %d; nad rezervo: deskriptorjev "
              "%s, pomnilnika %s MiB" % (razlog, kje or "-", int(VELJA_S // 60), n, "?" if prosti is None else prosti,
                                         "?" if prostega is None else prostega // (1024 * 1024)), flush=True)
    for p in poslusalci:
        try:
            p(razlog, kje, n)
        except Exception:  # noqa: BLE001 - obvestilo ne sme ustaviti Linka
            pass


def stanje() -> dict:
    """{"razlog", "kje", "zavrnjenih", "pred_s"} zadnjega pomanjkanja v zadnjih VELJA_S; sicer {}."""
    with _zaklep:
        ob = float(_stanje["ob"] or 0.0)
        if not _stanje["razlog"] or time.monotonic() - ob > VELJA_S:
            return {}
        return {"razlog": str(_stanje["razlog"]), "kje": str(_stanje["kje"]),
                "zavrnjenih": int(_stanje["zavrnjenih"] or 0), "pred_s": int(time.monotonic() - ob)}


#: Druge naprave, ki NAS niso sprejele zaradi svojih virov (odgovor `ni_virov`): ime -> cas zadnje zavrnitve.
_drugi: Dict[str, float] = {}
_drugi_obvesceni: Dict[str, float] = {}
#: Klici (ime naprave), ko nas druga naprava ni sprejela zaradi virov - najvec enkrat na OBVESTILO_VSAKIH_S za isto
#: napravo. Safeer Link (core/safeer_link.py) tu prijavi obvestilo namizja.
POSLUSALCI_DRUGIH: List[Callable[[str], None]] = []


def zavrnila_druga(ime: str) -> None:
    """Druga naprava v krogu nas je overila, a nima virov za nas (BREZ_VIROV, `ni_virov`): uporabnik to izve."""
    ime = " ".join(str(ime or "").split())[:64] or "?"
    zdaj = time.monotonic()
    with _zaklep:
        _drugi[ime] = zdaj
        for staro in [i for i, ob in _drugi.items() if zdaj - ob > VELJA_S]:
            _drugi.pop(staro, None)
        obvesti = zdaj - _drugi_obvesceni.get(ime, -1e18) >= OBVESTILO_VSAKIH_S
        if obvesti:
            _drugi_obvesceni[ime] = zdaj
        poslusalci = list(POSLUSALCI_DRUGIH) if obvesti else []
    if obvesti:
        print("[SafeerLink] viri: naprava %s nima virov za novo povezavo (odgovor %s)" % (ime, KODA), flush=True)
    for p in poslusalci:
        try:
            p(ime)
        except Exception:  # noqa: BLE001
            pass


def zavrnile_druge() -> List[str]:
    """Imena naprav, ki so nas v zadnjih VELJA_S zavrnile zaradi svojih virov (za vmesnik)."""
    zdaj = time.monotonic()
    with _zaklep:
        return sorted(i for i, ob in _drugi.items() if zdaj - ob <= VELJA_S)


def ponastavi() -> None:
    """Za preizkuse: brez zapisanega pomanjkanja, obvestilo spet takoj."""
    global _zadnje_obvestilo, _zadnji_dnevnik
    with _zaklep:
        _stanje.update(razlog="", kje="", ob=0.0, zavrnjenih=0)
        _zadnje_obvestilo = _zadnji_dnevnik = -1e18
        _drugi.clear()
        _drugi_obvesceni.clear()
    _zadnja_meritev[:] = [-1e18, 0.0]


# ------------------------------------------------------------------ besedila (sl, en, de, es, fr, it)

#: Na tej napravi (sredisce, ki clana ni moglo sprejeti): (naslov, besedilo) po razlogu.
BESEDILA: Dict[str, Dict[str, Tuple[str, str]]] = {
    "sl": {
        DESKRIPTORJI: ("Safeer Link: ni prostih povezav",
                       "Ta računalnik je dosegel sistemsko mejo hkrati odprtih povezav. Novih naprav iz kroga zdaj ne "
                       "sprejme (zavrnjenih: {n}). Zapri kakšen program ali znova zaženi Safeer."),
        POMNILNIK: ("Safeer Link: premalo pomnilnika",
                    "Temu računalniku zmanjkuje pomnilnika. Novih naprav iz kroga zdaj ne sprejme (zavrnjenih: {n}). "
                    "Zapri kakšen program; naprave se povežejo same, ko bo spet dovolj prostora."),
        NITI: ("Safeer Link: sistem ne dovoli več opravil",
               "Sistem ne dovoli več hkratnih opravil (niti). Novih naprav iz kroga zdaj ne sprejme (zavrnjenih: {n}). "
               "Zapri kakšen program ali znova zaženi Safeer."),
        KODA: ("Safeer Link: naprava je zasedena",
               "Naprava »{ime}« ima zdaj premalo virov (povezav ali pomnilnika) za novo povezavo. Poskusim znova sam."),
    },
    "en": {
        DESKRIPTORJI: ("Safeer Link: no free connections",
                       "This computer has reached the system limit of open connections. It does not accept new devices "
                       "from the circle right now (refused: {n}). Close a program or restart Safeer."),
        POMNILNIK: ("Safeer Link: low on memory",
                    "This computer is running out of memory. It does not accept new devices from the circle right now "
                    "(refused: {n}). Close a program; devices connect by themselves once there is room again."),
        NITI: ("Safeer Link: the system allows no more tasks",
               "The system allows no more simultaneous tasks (threads). New devices from the circle are not accepted "
               "right now (refused: {n}). Close a program or restart Safeer."),
        KODA: ("Safeer Link: device is busy",
               "The device “{ime}” has too few resources (connections or memory) for a new connection right now. "
               "I will try again by myself."),
    },
    "de": {
        DESKRIPTORJI: ("Safeer Link: keine freien Verbindungen",
                       "Dieser Computer hat die Systemgrenze offener Verbindungen erreicht. Er nimmt gerade keine neuen "
                       "Geräte aus dem Kreis an (abgelehnt: {n}). Schließe ein Programm oder starte Safeer neu."),
        POMNILNIK: ("Safeer Link: wenig Arbeitsspeicher",
                    "Diesem Computer geht der Arbeitsspeicher aus. Er nimmt gerade keine neuen Geräte aus dem Kreis an "
                    "(abgelehnt: {n}). Schließe ein Programm; die Geräte verbinden sich von selbst, sobald wieder Platz ist."),
        NITI: ("Safeer Link: das System erlaubt keine weiteren Aufgaben",
               "Das System erlaubt keine weiteren gleichzeitigen Aufgaben (Threads). Neue Geräte aus dem Kreis werden "
               "gerade nicht angenommen (abgelehnt: {n}). Schließe ein Programm oder starte Safeer neu."),
        KODA: ("Safeer Link: Gerät ist ausgelastet",
               "Das Gerät „{ime}“ hat gerade zu wenige Ressourcen (Verbindungen oder Arbeitsspeicher) für eine neue "
               "Verbindung. Ich versuche es selbst erneut."),
    },
    "es": {
        DESKRIPTORJI: ("Safeer Link: no hay conexiones libres",
                       "Este ordenador ha alcanzado el límite del sistema de conexiones abiertas. Ahora no acepta nuevos "
                       "dispositivos del círculo (rechazados: {n}). Cierra algún programa o reinicia Safeer."),
        POMNILNIK: ("Safeer Link: poca memoria",
                    "A este ordenador se le está acabando la memoria. Ahora no acepta nuevos dispositivos del círculo "
                    "(rechazados: {n}). Cierra algún programa; los dispositivos se conectarán solos cuando vuelva a haber sitio."),
        NITI: ("Safeer Link: el sistema no permite más tareas",
               "El sistema no permite más tareas simultáneas (hilos). Ahora no se aceptan nuevos dispositivos del "
               "círculo (rechazados: {n}). Cierra algún programa o reinicia Safeer."),
        KODA: ("Safeer Link: el dispositivo está ocupado",
               "El dispositivo «{ime}» tiene ahora pocos recursos (conexiones o memoria) para una nueva conexión. "
               "Lo volveré a intentar yo solo."),
    },
    "fr": {
        DESKRIPTORJI: ("Safeer Link : plus de connexions libres",
                       "Cet ordinateur a atteint la limite système de connexions ouvertes. Il n'accepte plus de nouveaux "
                       "appareils du cercle pour l'instant (refusés : {n}). Ferme un programme ou redémarre Safeer."),
        POMNILNIK: ("Safeer Link : mémoire insuffisante",
                    "Cet ordinateur manque de mémoire. Il n'accepte plus de nouveaux appareils du cercle pour l'instant "
                    "(refusés : {n}). Ferme un programme ; les appareils se connecteront seuls dès qu'il y aura de la place."),
        NITI: ("Safeer Link : le système n'autorise plus de tâches",
               "Le système n'autorise plus de tâches simultanées (threads). Les nouveaux appareils du cercle ne sont "
               "pas acceptés pour l'instant (refusés : {n}). Ferme un programme ou redémarre Safeer."),
        KODA: ("Safeer Link : appareil occupé",
               "L'appareil « {ime} » manque pour l'instant de ressources (connexions ou mémoire) pour une nouvelle "
               "connexion. Je réessaierai tout seul."),
    },
    "it": {
        DESKRIPTORJI: ("Safeer Link: nessuna connessione libera",
                       "Questo computer ha raggiunto il limite di sistema delle connessioni aperte. Ora non accetta nuovi "
                       "dispositivi della cerchia (rifiutati: {n}). Chiudi un programma o riavvia Safeer."),
        POMNILNIK: ("Safeer Link: memoria insufficiente",
                    "Questo computer sta esaurendo la memoria. Ora non accetta nuovi dispositivi della cerchia "
                    "(rifiutati: {n}). Chiudi un programma; i dispositivi si collegheranno da soli quando ci sarà di nuovo spazio."),
        NITI: ("Safeer Link: il sistema non consente altre attività",
               "Il sistema non consente altre attività simultanee (thread). I nuovi dispositivi della cerchia non "
               "vengono accettati ora (rifiutati: {n}). Chiudi un programma o riavvia Safeer."),
        KODA: ("Safeer Link: dispositivo occupato",
               "Il dispositivo «{ime}» ha ora poche risorse (connessioni o memoria) per una nuova connessione. "
               "Riproverò da solo."),
    },
}

#: Primarni jezik prikaza Windows (spodnjih 10 bitov oznake jezika) -> nasa koda.
_JEZIKI_WINDOWS = {0x24: "sl", 0x09: "en", 0x07: "de", 0x0A: "es", 0x0C: "fr", 0x10: "it"}


def jezik() -> str:
    """Jezik obvestil po istem vrstnem redu kot ostali Safeer (LANGUAGE, LC_ALL, LC_MESSAGES, LANG), na Windows jezik
    prikaza; "en", ce jezika ne poznamo."""
    for kljuc in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        vrednost = (os.environ.get(kljuc) or "").strip().lower()
        if vrednost and vrednost not in ("c", "posix"):
            koda = vrednost.split(":")[0][:2]
            return koda if koda in BESEDILA else "en"
    if sys.platform == "win32":
        try:
            import ctypes
            koda = int(ctypes.windll.kernel32.GetUserDefaultUILanguage()) & 0x3FF  # type: ignore[attr-defined]
            return _JEZIKI_WINDOWS.get(koda, "en")
        except Exception:  # noqa: BLE001
            pass
    return "en"


def besedilo(razlog: str, jezik_: Optional[str] = None, **p) -> Tuple[str, str]:
    """(naslov, besedilo) v jeziku uporabnika; neznan razlog = pomnilnik (splosno)."""
    b = BESEDILA.get(str(jezik_ or jezik())[:2]) or BESEDILA["en"]
    naslov, telo = b.get(razlog) or b[POMNILNIK]
    vrednosti = {"n": p.get("n", p.get("zavrnjenih", "")), "ime": p.get("ime", "")}
    return naslov, telo.format(**{k: str(v) for k, v in vrednosti.items()})


__all__ = ["preveri", "zabelezi", "stanje", "besedilo", "jezik", "rezerva_diska", "zazeni_nit", "zavrnila_druga",
           "zavrnile_druge", "prostih_deskriptorjev", "prostega_pomnilnika", "KODA", "DESKRIPTORJI", "POMNILNIK",
           "NITI"]
