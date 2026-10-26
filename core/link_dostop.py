"""Dostop drugih naprav v Safeer Linku do vsebin TEGA racunalnika (ista pravila kot cast/DostopPravila.kt na Androidu).

Seznanitev v Safeer Link ni dovoljenje za vsebine. Safeer Link je sirsi krog (»EU«): vsaka naprava v njem pomaga pri
povezavi (sredisce, posredovanje, pot prek mobilnega omrezja) in sprejme, kar ji kdo izrecno poslje. Dostop do vsebin
je ozji krog (»Schengen«): na VSAKI napravi posebej in za VSAKO drugo napravo posebej uporabnik odloci, kaj ji odpre -
datoteke, programe, predvajalnik, zaslon in upravljanje. Brez tega racunalnik zahtevo zavrne sam.

Prej je bila vsaka seznanjena naprava enakovredna in stikala (mape, programi, zaslon, predvajanje) so veljala za ves
Link: telefon druge osebe, dodan v Link, je takoj dobil vse, kar racunalnik deli (izmerjeno 6. 10. 2026).

Zapis (dostop.json v mapi nastavitev, 0600; berejo ga Control, brskalnik in sredisce na tem racunalniku):
  {"v": 1, "podedovano_ob": 1791300000.0, "naprave": {"n-<16 hex>": "dpvz"}, "zascita": ["n-<16 hex>"]}
»zascita«: naprave, ki so s tem racunalnikom ze vzpostavile zascito od naprave do naprave (core/link_e2e). Od take
naprave nezascitenega ukaza ne sprejmemo vec - sicer bi se kdorkoli z njeno oznako predstavil kot starejsa razlicica.
Crke: d = datoteke, p = programi, v = predvajalnik, z = zaslon in upravljanje. Naprava brez zapisa nima dostopa.
»zavrnjeno«: {"n-<16 hex>|<crka>": unix cas} - prosnje za dostop, ki jih je uporabnik tu zavrnil (24 ur brez vprasanja;
glej prosnje za dostop spodaj). Polja, ki jih program ne pozna, ob pisanju ostanejo.
Ob prvem zagonu z dovoljenji se enkrat vpisejo naprave, ki so bile z racunalnikom v krogu ze prej (`podedovani`);
pozneje se nic vec ne podeduje - nov vnos v krogu s starim datumom dostopa ne dobi. Da je dedovanje ze bilo, pove svoja
oznaka ob zapisu (dostop.json.podedovano): zapis, ki pozneje izgine (rocno ciscenje, obnova brez te datoteke), ne podeduje
znova - dostopa nima nihce (sedmi pregled, 25. 10. 2026: prej so naprave znova dobile vse, tudi tiste, ki jim je
uporabnik dostop vzel). Podedovane naprave ne dobijo ozjega kroga (upravljanje, Safeer Vnos, domaca mapa): ta je samo
z izrecno privolitvijo (lastnik 25. 10. 2026 10:49).

Zapis pise VEC programov tega racunalnika hkrati (ko naprava dokaze kljuc, to zabelezi vsak program, ki jo vidi). Zato je
vsako pisanje en korak pod zaklepom datoteke: stanje z diska -> sprememba -> zapis v svojo zacasno datoteko -> zamenjava
(glej _spremeni). Prej je vsak program pisal stanje iz svojega pomnilnika v skupno `dostop.json.tmp`: izmerjeno
7. 10. 2026 sta dva programa pri socasnem pisanju padla (FileNotFoundError) in spremembe so se izgubljale.

Varna stran ob napakah (peti neodvisni pregled, 7. 10. 2026):
- Zapisa NI (prvi zagon): dosedanje naprave podedujejo. Zapis JE, a ga ni mogoce pregledati ali prebrati (pravice,
  napaka diska): dostopa nima nihce, nicesar ne pisemo (NapakaBranja) - »ne vem« ni »ni«. Prej je program ob taki
  napaki veljaven zapis zamenjal s praznim ali pa v pomnilniku znova podedoval.
- Starejsi program na istem racunalniku polja »zascita« ne pozna in ga ob svojem pisanju izpusti: ta program ga ob
  naslednji potrditvi seje vrne na disk (zabelezi_zascito).
- Na zaklep datoteke cakamo najvec ZAKLEP_CAKA_S: zamrznjen program, ki ga drzi, ne sme ustaviti tega.
- Tik pred zamenjavo datoteke preverimo, da je zapis se tak, kot smo ga prebrali; ce ga je vmes spremenil drug program
  (pisal je brez zaklepa ali pa smo brez zaklepa mi), preberemo znova in spremembo ponovimo. Brez tega je program, ki je
  zaklep predolgo drzal, povozil spremembo drugega - tudi odvzem dostopa (sesti pregled, 7. 10. 2026).
- Brez te preverbe ne pisemo nikoli (sedmi pregled, 25. 10. 2026: zadnji poskus je pisal brez nje in lahko razveljavil
  umik, ki ga je vmes zapisal drug program). Ce se zapis spreminja pod nami ves cas, sprememba ne uspe (NapakaZapisa) in
  uporabnik to vidi - raje napaka kot tiho povozen odvzem.
"""
from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import weakref
from collections import OrderedDict
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

#: 6. 10. 2026 00:00:00 UTC. Naprave, ki so bile s to napravo v krogu ze prej, ob uvedbi dovoljenj obdrzijo dostop.
MEJA_PODEDOVANJA = 1_791_244_800.0
#: Najdlje toliko cakamo na zaklep zapisa, ki ga drzi drug program; potem pisemo brez zaklepa (zamenjava je en korak).
ZAKLEP_CAKA_S = 2.0
#: Po zapisu, ki ni uspel, popravila zapisa »zascita« toliko casa ne poskusamo znova (glej zabelezi_zascito).
POPRAVILO_PO_NEUSPEHU_S = 60.0
#: Kolikokrat preberemo znova, ce se zapis med pripravo nasega spremeni; potem sprememba ne uspe (NapakaZapisa).
NAJVEC_POSKUSOV_ZAPISA = 4


class NapakaBranja(OSError):
    """Zapis dovoljenj obstaja, a ga trenutno ni mogoce pregledati ali prebrati. Ne beremo, ne pisemo, nihce nima dostopa."""


class NapakaZapisa(OSError):
    """Zapis se je med vsemi poskusi spreminjal pod nami (drug program pise): nasa sprememba NI zapisana."""

DATOTEKE, PROGRAMI, PREDVAJALNIK, ZASLON = "d", "p", "v", "z"
VSE_ZMOZNOSTI = frozenset((DATOTEKE, PROGRAMI, PREDVAJALNIK, ZASLON))
#: Kaj zahteva dejanje: "" = prosto (vsaka naprava v Linku), crka zmoznosti ali "*" = vse (samo ozji krog).
PROSTO, VSE = "", "*"

_DEJANJA = {
    # files.session: Teamwork - naprava pove, da ima datoteko te naprave odprto (core/link_teamwork).
    DATOTEKE: {"files.list", "files.search", "files.open", "files.open_locen", "files.session", "storage.put", "storage.status"},
    PROGRAMI: {"apps.list", "apps.launch", "apps.launch_locen", "apps.close", "apps.running", "apps", "launch_app", "open_in_app"},
    PREDVAJALNIK: {
        # Kaj naprava predvaja, nadaljevanje in ustavitev; seznami in viri Medijskega centra.
        "play.state", "play.stop", "lists.get",
        # Odpiranje vsebine na tej napravi brez vprasanja in zvok druge naprave na njenih zvocnikih.
        "open_url", "magnet.open", "audio.play", "audio.stop", "media.open",
        # Pomoc pri predvajanju vidi, kaj druga naprava gleda, in trosi to napravo (prenos, pretvorba, dodatki).
        "magnet.stream", "magnet.list", "magnet.remove", "magnet.keep",
        "video.transcode", "video.status", "video.stream", "video.stream_stop", "video.stream_status",
        "avail.get", "host.info",
    },
    ZASLON: {"screen.start", "screen.stop", "screen.status", "screen.thumb", "key", "scroll", "screenshot", "search.query",
             "volume", "restart", "clear_cache", "status"},
}


def zahteva_dejanja(dejanje: str) -> str:
    """Kaj zahteva ukaz `control.command`. Ponudba »Poslji na napravo« (`play.offer`) je prosta: nic se ne zacne,
    dokler uporabnik tu ne sprejme. Neznano dejanje zahteva vse - novo dejanje ni odprto po pomoti."""
    d = (dejanje or "").strip().lower()
    if d == "play.offer":
        return PROSTO
    for zmoznost, dejanja in _DEJANJA.items():
        if d in dejanja:
            return zmoznost
    if d.startswith("input.") or d.startswith("gamepad."):
        return ZASLON
    return VSE


def zahteva_sporocila(tip: str, dejanje: str = "") -> str:
    """Kaj zahteva sporocilo, ki ni ukaz. Besedilo, datoteka in klepet so izrecno poslani (prosto). Stran ali
    predvajanje, ki se odpre samo, zahteva predvajalnik; usklajevanje (zaznamki, stanje) samo ozji krog; zaslon druge
    naprave, ki se tu odpre sam, zahteva zaslon. Konec deljenja je vedno dovoljen."""
    if tip in ("cast.url", "cast.control", "cast.media", "handoff.request"):
        return PREDVAJALNIK
    if tip == "sync.data":
        return VSE
    if tip == "share.screen":
        return PROSTO if dejanje == "stop" else ZASLON
    return PROSTO


def sme_z(dano: Iterable[str], zahteva: str) -> bool:
    dano = set(dano)
    if zahteva == PROSTO:
        return True
    if zahteva == VSE:
        return VSE_ZMOZNOSTI <= dano
    return zahteva in dano


def iz_niza(s: Optional[str]) -> Set[str]:
    return {c for c in (s or "") if c in VSE_ZMOZNOSTI}


#: Kar ozji krog dobi vedno: upravljanje s Safeer Vnos in uporabnikove mape (domaca mapa, link_datoteke.DeljeneMape.dom).
OZJI_KROG = frozenset((DATOTEKE, ZASLON))


def ozji_krog(dano: Iterable[str]) -> Set[str]:
    """Pravilo lastnika (25. 10. 2026 10:49, velja povsod): naprava, ki jo uporabnik da v ozji krog (katerakoli
    zmoznost), dobi z ISTO privolitvijo tudi upravljanje tega racunalnika in Safeer Vnos (ZASLON: zaslon, miska,
    tipkovnica, input.*) in uporabnikove mape (DATOTEKE; brez skritih map in skrivnosti - odlocitev vodje 25. 10.
    po istem pravilu) - brez locenih stikal. Prazen nabor ostane prazen (naprava samo pomaga pri povezavi).
    Zapisov, ki so nastali pred tem pravilom, ne siri samo od sebe: velja ob naslednji privolitvi uporabnika.
    Uporabi se SAMO na poti izrecne privolitve (nastavi_ozji_krog: stikalo v oknu Link; odobri_prosnjo: »Dovoli«);
    nastavi in dodaj_zmoznost(i) sta natancni - nova koda z njima ne podeli upravljanja po pomoti (sedmi pregled)."""
    nabor = {c for c in (dano or ()) if c in VSE_ZMOZNOSTI}
    return nabor | OZJI_KROG if nabor else nabor


def v_niz(dano: Iterable[str]) -> str:
    dano = set(dano)
    return "".join(c for c in (DATOTEKE, PROGRAMI, PREDVAJALNIK, ZASLON) if c in dano)


DOLZINA_JEDRA = 18


_PRIPONA_OZNAKE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
NAJVEC_OZNAKE = 128


def je_id_iz_kljuca(device_id: str) -> bool:
    """Oznaka iz kljuca: `n-<16 hex>`, po zelji s pripono programa iz crk, stevk, pike, podcrtaja in vezaja (isto
    pravilo kot link_krog.je_id_iz_kljuca). Oznaka z drugimi znaki ni oznaka iz kljuca."""
    if not isinstance(device_id, str) or not (DOLZINA_JEDRA <= len(device_id) <= NAJVEC_OZNAKE):
        return False
    if not device_id.startswith("n-") or any(z not in "0123456789abcdef" for z in device_id[2:DOLZINA_JEDRA]):
        return False
    if len(device_id) == DOLZINA_JEDRA:
        return True
    return device_id[DOLZINA_JEDRA] == "-" and all(z in _PRIPONA_OZNAKE for z in device_id[DOLZINA_JEDRA + 1:])


def jedro_iz(device_id: str, kljuc_clana: Callable[[str], Optional[str]], id_iz_kljuca: Callable[[str], str]) -> str:
    """Stalna oznaka naprave ne glede na id, pod katerim se javi. Odloca KLJUC, pod katerim je naprava v krogu:

    - id iz kljuca (`n-<16 hex>`, po zelji s pripono sorodnika `-os`, `-control` ...) da svoje jedro - RAZEN ce je pod
      tem id-jem v krogu vpisan drug kljuc. Tak vnos je videti kot druga naprava, a to ni (izmerjeno 7. 10. 2026: krog ga
      je sprejel in preverba dostopa mu je dala dostop posnemane naprave); dobi prazno jedro, torej nic.
    - star id se prevede prek kljuca v krogu; naprava, ki je krog ne pozna, ostane pri svojem id-ju (zanjo ni zapisa,
      torej nima dostopa)."""
    device_id = str(device_id or "")
    try:
        kljuc = kljuc_clana(device_id)
        jedro_kljuca = id_iz_kljuca(kljuc) if kljuc else ""
    except Exception:  # noqa: BLE001 - pokvarjen kljuc ne sme odpreti nicesar
        return ""
    if je_id_iz_kljuca(device_id):
        if jedro_kljuca and jedro_kljuca != device_id[:DOLZINA_JEDRA]:
            return ""
        return device_id[:DOLZINA_JEDRA]
    return jedro_kljuca or device_id


def podedovani(clani: Iterable[dict], lastni_kljuc: Optional[str], id_iz_kljuca: Callable[[str], str],
               meja: float = MEJA_PODEDOVANJA) -> Set[str]:
    """Naprave (jedra), ki ob uvedbi dovoljenj obdrzijo dostop: tiste, ki so v krogu ze od prej kot `meja` - a le, ce
    je bila v krogu ze prej tudi TA naprava. Naprava, dodana po meji (telefon druge osebe, nova namestitev), ne podeduje
    nikogar. Steje najstarejsi veljavni vnos istega kljuca (naprava ima lahko vec id-jev)."""
    if not lastni_kljuc:
        return set()
    najstarejsi: Dict[str, float] = {}
    for c in clani:
        kljuc = str(c.get("kljuc") or "")
        if not kljuc:
            continue
        try:
            dodano = float(c.get("dodano") or 0.0)
        except (TypeError, ValueError):
            continue
        if kljuc not in najstarejsi or dodano < najstarejsi[kljuc]:
            najstarejsi[kljuc] = dodano
    nas = najstarejsi.get(lastni_kljuc)
    if nas is None or nas >= meja:
        return set()
    izid: Set[str] = set()
    for kljuc, dodano in najstarejsi.items():
        if kljuc == lastni_kljuc or dodano >= meja:
            continue
        try:
            izid.add(id_iz_kljuca(kljuc))
        except Exception:  # noqa: BLE001
            pass
    return izid


def zavrnitev(dejanje: str) -> dict:
    """Odgovor napravi, ki ji uporabnik zmoznosti ni odprl. Pri seznamih ima obliko »naprava tega ne deli«, kot jo
    naprave ze poznajo (prazen seznam, shared/enabled = false) - starejsa razlicica na drugi strani ne pokaze napake,
    ampak napravo brez deljenja. Vse drugo dobi kratko zavrnitev s kodo."""
    d = (dejanje or "").strip().lower()
    if d in ("files.list", "files.search"):
        return {"ok": True, "message": "Naprava datotek ne deli",
                "data": {"folder": "", "items": [], "shared": False, "reason": "access"}}
    if d == "apps.list":
        return {"ok": True, "message": "Računalnik programov ne deli", "data": {"items": [], "enabled": False, "reason": "access"}}
    if d == "apps.running":
        return {"ok": True, "message": "Odprti programi", "data": {"running": [], "reason": "access"}}
    if d == "play.state":
        return {"ok": True, "message": "Predvajanje", "data": {"shared": False, "reason": "access"}}
    return {"ok": False, "message": "Ta naprava ti tega ne dovoli. Dostop odpre njen uporabnik v Safeer Linku.",
            "code": "ni_dovoljeno"}


# ---------------------------------------------------------------------- zapis na tem racunalniku

_zaklep = threading.RLock()
_zapis: Optional[Dict[str, Set[str]]] = None
_zascita: Set[str] = set()
#: Po cem prepoznamo, da je zapis na disku spremenil drug program: (cas spremembe v ns, stevilka datoteke, velikost).
#: Samo cas ni dovolj - dva zapisa v istem trenutku imata lahko isti cas; vsak zapis pa je nova datoteka.
_prebran_odtis: Optional[Tuple[int, int, int]] = None
_prebrana_pot = ""
_pot_preglasena: Optional[str] = None
#: Kar je bilo v polju »zascita« na disku, ko smo ga nazadnje prebrali ali zapisali (v pomnilniku je lahko vec).
_zascita_disk: Set[str] = set()
#: Kdaj (time.monotonic) zapis nazadnje ni uspel; None = zadnji je uspel.
_zapis_spodletel_ob: Optional[float] = None
#: Polje »zavrnjeno« z diska (glej prosnje spodaj): "<jedro>|<crka>" -> cas zavrnitve (unix).
_zavrnjeno_disk: Dict[str, float] = {}
#: Polje »dom« z diska: jedra z izrecno privolitvijo za domaco mapo v tej razlicici (glej sme_domaco_mapo).
_dom_disk: Set[str] = set()


def _pot() -> str:
    if _pot_preglasena:
        return _pot_preglasena
    from core import link_hub
    return os.path.join(link_hub.NASTAVITVE_MAPA, "dostop.json")


def _pot_oznake(pot: str) -> str:
    """Oznaka »dedovanje je ze bilo« ob zapisu (loceno od njega: izgine samo, ce izgine cela mapa nastavitev)."""
    return pot + ".podedovano"


def _dedovanje_opravljeno(pot: str) -> bool:
    """Ali je ta racunalnik naprave ze podedoval. Oznake ni mogoce pregledati -> da (varna stran: brez dedovanja)."""
    try:
        os.lstat(_pot_oznake(pot))
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _zabelezi_dedovanje(pot: str) -> None:
    """Oznaka, da je dedovanje opravljeno (enkrat; napaka ni usodna - zapis dovoljenj sam ostane)."""
    oznaka = _pot_oznake(pot)
    if os.path.lexists(oznaka):
        return
    try:
        rocaj, zacasna = tempfile.mkstemp(prefix=os.path.basename(oznaka) + ".", suffix=".tmp",
                                          dir=os.path.dirname(oznaka))
        try:
            with os.fdopen(rocaj, "w", encoding="utf-8") as d:
                json.dump({"v": 1, "ob": time.time()}, d)
                d.flush()
                os.fsync(d.fileno())
            os.replace(zacasna, oznaka)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(zacasna)
            raise
        _fsync_mape(os.path.dirname(oznaka))
    except OSError as e:
        print(f"[SafeerDostop] oznake dedovanja ni bilo mogoce zapisati: {e}")


def _fsync_mape(mapa: str) -> None:
    """Zamenjava datoteke je trajna sele, ko je na disku tudi mapa (izpad napajanja ne vrne zapisa pred umikom).
    Kjer mape ni mogoce odpreti (Windows), ostane fsync datoteke."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        rocaj = os.open(mapa or ".", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return
    try:
        os.fsync(rocaj)
    except OSError:
        pass
    finally:
        os.close(rocaj)


def _krog():
    from core import link_krog
    return link_krog.krog()


def _lastni_kljuc() -> Optional[str]:
    from core import link_krog
    try:
        return link_krog.javni_kljuc_b64()
    except Exception:  # noqa: BLE001
        return None


def _id_iz_kljuca(kljuc: str) -> str:
    from core import link_krog
    return link_krog.id_iz_kljuca(kljuc)


def _odtis_zapisa(pot: str) -> Optional[Tuple[int, int, int]]:
    """Odtis zapisa na disku ali None, ce zapisa NI. Vsaka druga napaka (pravice, disk) vrze NapakaBranja."""
    try:
        st = os.stat(pot)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise NapakaBranja(e.errno, "zapisa dovoljenj ni mogoce pregledati") from e
    return (st.st_mtime_ns, st.st_ino, st.st_size)


@contextlib.contextmanager
def _zaklenjen_zapis(pot: str):
    """Zaklep zapisa med PROGRAMI tega racunalnika. Zaklep je svoja datoteka ob zapisu (zapis sam se ob vsakem pisanju
    zamenja z novo datoteko). Kjer zaklepa ni (ni fcntl, datoteke ni mogoce odpreti), ostane zaklep v programu -
    slabse, a zapis mora delovati."""
    rocaj = None
    try:
        try:
            import fcntl
            # Brez sledenja simbolni povezavi (podtaknjena .lock ne ustvari datoteke drugje) in brez dedovanja v
            # podprocese (sedmi pregled, 25. 10. 2026).
            rocaj = os.open(pot + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                            | getattr(os, "O_CLOEXEC", 0), 0o600)
            # Brez cakanja v jedru: program, ki zaklep drzi in stoji (zamrznjen, v razhroscevalniku), bi nas sicer
            # ustavil za vedno - in z nami vse preverbe dostopa. Po ZAKLEP_CAKA_S pisemo brez zaklepa (pred zamenjavo
            # datoteke se vedno preverimo, da je zapis nespremenjen - glej _spremeni).
            rok = time.monotonic() + ZAKLEP_CAKA_S
            while True:
                try:
                    fcntl.flock(rocaj, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= rok:
                        break
                    time.sleep(0.01)
                except OSError:
                    break       # zaklepanje tu ni mogoce (datotecni sistem ga ne podpira): ne cakamo
        except Exception:  # noqa: BLE001
            pass
        yield
    finally:
        if rocaj is not None:
            try:
                os.close(rocaj)         # zaprtje zaklep sprosti
            except OSError:
                pass


#: Polja zapisa, ki jih pise _na_disk sam; vsa druga (»zavrnjeno« in polja novejsih programov) ostanejo, kot so.
_LASTNA_POLJA = ("v", "podedovano_ob", "naprave", "zascita")


def _z_diska(pot: str) -> Tuple[str, Dict[str, Set[str]], Set[str], float, dict]:
    """Zapis na disku: (stanje, naprave, zascita, podedovano_ob, ostalo). Stanje je "ok", "ni" (datoteke ni), "napaka"
    (datoteka je, a je ni mogoce prebrati - pravice, disk) ali "pokvarjen" (vsebina ni pravilen zapis); razen pri "ok"
    so naprave, zascita in ostalo prazni. `ostalo` so polja, ki jih ta zapis sam ne vodi (npr. »zavrnjeno«, polja
    novejsega programa): ob pisanju jih vrnemo nespremenjena."""
    try:
        with open(pot, "r", encoding="utf-8") as d:
            besedilo = d.read()
    except FileNotFoundError:
        return "ni", {}, set(), 0.0, {}
    except OSError:
        return "napaka", {}, set(), 0.0, {}
    except ValueError:
        return "pokvarjen", {}, set(), 0.0, {}
    try:
        surovo = json.loads(besedilo) or {}
        naprave = {str(k): iz_niza(str(crke)) for k, crke in (surovo.get("naprave") or {}).items()}
        zascita = {str(j) for j in (surovo.get("zascita") or []) if isinstance(j, str) and je_id_iz_kljuca(j)}
        try:
            ob = float(surovo.get("podedovano_ob") or 0.0)
        except (TypeError, ValueError):
            ob = 0.0
        ostalo = {str(k): v for k, v in surovo.items() if k not in _LASTNA_POLJA}
        return "ok", naprave, zascita, ob, ostalo
    except Exception:  # noqa: BLE001
        return "pokvarjen", {}, set(), 0.0, {}


_NE_PREVERJAJ = object()


def _na_disk(pot: str, naprave: Dict[str, Set[str]], zascita: Set[str], podedovano_ob: float,
             pricakovan: object = _NE_PREVERJAJ, ostalo: Optional[dict] = None) -> Optional[Tuple[int, int, int]]:
    """Zapis v SVOJO zacasno datoteko (0600) in zamenjava: nikoli pol zapisa, nikoli datoteka, ki bi jo hkrati pisal
    drug program. Vrne odtis novega zapisa (zamenjava ohrani stevilko datoteke, cas in velikost zacasne datoteke).

    `pricakovan` je odtis zapisa, kot smo ga prebrali (None = zapisa ni bilo): ce je zapis tik pred zamenjavo drugacen,
    ga je vmes spremenil drug program - NE zamenjamo in vrnemo None (klicatelj prebere znova in spremembo ponovi).
    `ostalo` so polja, ki jih ta zapis ne vodi (prebrana z diska): zapisejo se nespremenjena."""
    vsebina = {k: v for k, v in (ostalo or {}).items() if k not in _LASTNA_POLJA}
    vsebina.update({"v": 1, "podedovano_ob": podedovano_ob, "naprave": {k: v_niz(v) for k, v in sorted(naprave.items())},
                    "zascita": sorted(zascita)})
    rocaj, zacasna = tempfile.mkstemp(prefix=os.path.basename(pot) + ".", suffix=".tmp", dir=os.path.dirname(pot))
    try:
        with os.fdopen(rocaj, "w", encoding="utf-8") as d:
            json.dump(vsebina, d, indent=1)
            d.flush()
            if hasattr(os, "fchmod"):                  # Windows (Python pred 3.13) ga nima; mkstemp ze da 0600
                os.fchmod(d.fileno(), 0o600)
            os.fsync(d.fileno())
            st = os.fstat(d.fileno())
        if pricakovan is not _NE_PREVERJAJ and _odtis_zapisa(pot) != pricakovan:
            os.unlink(zacasna)
            return None
        os.replace(zacasna, pot)
        _fsync_mape(os.path.dirname(pot))
        return (st.st_mtime_ns, st.st_ino, st.st_size)
    except BaseException:
        try:
            os.unlink(zacasna)
        except OSError:
            pass
        raise


#: Kar podedovana naprava obdrzi: programi in predvajalnik. Ozji krog (upravljanje s Safeer Vnos, domaca mapa) samo z
#: izrecno privolitvijo uporabnika (lastnik 25. 10. 2026 10:49; sedmi pregled: prej je dedovanje dalo vse stiri).
PODEDOVANO = frozenset(VSE_ZMOZNOSTI - OZJI_KROG)


def _podedovana_jedra() -> Set[str]:
    try:
        k = _krog()
        with k._zaklep:
            clani = [dict(c) for c in k.clani.values() if k._veljaven(c)]
        return podedovani(clani, _lastni_kljuc(), _id_iz_kljuca)
    except Exception:  # noqa: BLE001 - brez kroga ni podedovanih
        return set()


def _podedovana_jedra_ali_none(naprave: Dict[str, Set[str]], izrecna: Iterable[str] = ()) -> Optional[Set[str]]:
    """Podedovana jedra za migracijo starega zapisa ali None, ce jih ni mogoce dolociti: kroga ali kljuca te naprave ni
    mogoce prebrati ali pa je krog prazen, zapis pa ima naprave z vsemi stirimi (krog.json izgubljen ali se ne prenesen).
    »Ne vem« ni »nobena«: prej se je oznaka dedovanja zapisala brez zmanjsanja in migracije ni bilo nikoli vec
    (pregled 17, M1). Naprave z izrecno privolitvijo v tej razlicici (`izrecna`, _izrecna) ne stejejo: prazen krog z
    njimi ne caka (pregled 29, G2: prej je migracija pri praznem krogu cakala trajno)."""
    izrecna = set(izrecna)
    try:
        k = _krog()
        with k._zaklep:
            clani = [dict(c) for c in k.clani.values() if k._veljaven(c)]
        kljuc = _lastni_kljuc()
        if not kljuc:
            return None
        if not clani and any(set(d) == set(VSE_ZMOZNOSTI) and j not in izrecna for j, d in naprave.items()):
            return None
        return podedovani(clani, kljuc, _id_iz_kljuca)
    except Exception:  # noqa: BLE001
        return None


def _brez_ozjega(naprave: Dict[str, Set[str]], jedra: Optional[Set[str]] = None,
                 izrecna: Iterable[str] = ()) -> Dict[str, Set[str]]:
    """Kopija zapisa, v kateri naprave z vsemi stirimi (`jedra` ali vse, ce None) nimajo ozjega kroga (PODEDOVANO).
    Naprave z izrecno privolitvijo v tej razlicici (`izrecna`, _izrecna) ostanejo, kot so (pregled 29, G2)."""
    vse, izrecna = set(VSE_ZMOZNOSTI), set(izrecna)
    return {j: (set(PODEDOVANO) if set(d) == vse and (jedra is None or j in jedra) and j not in izrecna else set(d))
            for j, d in naprave.items()}


def _podedovane_naprave() -> Dict[str, Set[str]]:
    """Prvi zagon z dovoljenji: dosedanje naprave obdrzijo programe in predvajalnik; pozneje dodane zacnejo brez dostopa."""
    return {j: set(PODEDOVANO) for j in _podedovana_jedra()}


#: Umiki iz kroga, ki jih ni bilo mogoce zapisati (poln disk, NapakaZapisa): jedro -> meja (None = vse; cas umika =
#: samo pravice, dane pred njim, ko se naprava vraca - glej ob_umiku_iz_kroga). V tem programu nimajo nicesar; vsak
#: zapis jih uveljavi, ponavlja jih casovnik v svoji niti (pregled 11, N3; pregled 17, M4 in M5).
_cakajo_umik: Dict[str, Optional[float]] = {}
_umik_casovnik: Optional[threading.Timer] = None
UMIK_PONOVI_S = 5.0
#: Kdaj (time.monotonic) je migracija starega zapisa nazadnje cakala na krog (None = ne caka); _nalozen jo ponovi.
_migracija_caka_ob: Optional[float] = None


def _dano_ob(ostalo: dict) -> Dict[str, float]:
    """Polje »dano_ob« zapisa: jedro -> kdaj (unix, ura tega racunalnika) je naprava nazadnje dobila kaj novega."""
    surovo = ostalo.get("dano_ob") if isinstance(ostalo, dict) else None
    izid: Dict[str, float] = {}
    if isinstance(surovo, dict):
        for j, t in surovo.items():
            try:
                izid[str(j)] = float(t)
            except (TypeError, ValueError):
                continue
    return izid


def _dom_iz(ostalo: dict) -> Set[str]:
    """Polje »dom« zapisa: jedro -> cas izrecne privolitve za domaco mapo (unix). Samo prava jedra."""
    surovo = ostalo.get("dom") if isinstance(ostalo, dict) else None
    return {str(j) for j in surovo if _je_jedro(j)} if isinstance(surovo, dict) else set()


def _izrecna(ostalo: dict) -> Set[str]:
    """Jedra z izrecno privolitvijo v tej razlicici: »dano_ob« (uporabnik je dal novo zmoznost) ali »dom«. Zapis
    prejsnje razlicice teh polj nima. Migracija starega zapisa in cakanje nanjo takih naprav ne zmanjsata (pregled 29,
    G2: prej je cakajoca migracija vzela upravljanje in Safeer Vnos tudi napravi, ki ji je uporabnik pravkar dal vse
    stiri, okno pa je javilo »Shranjeno«; ko je migracija stekla, je tiho vzela se domaco mapo)."""
    return set(_dano_ob(ostalo)) | _dom_iz(ostalo)


def _dovoli_dom(j: str, ostalo: dict) -> None:
    surovo = ostalo.get("dom")
    dom = dict(surovo) if isinstance(surovo, dict) else {}
    dom[j] = time.time()
    ostalo["dom"] = dom


def _pocisti_dom(naprave: Dict[str, Set[str]], ostalo: dict) -> None:
    """Privolitev za domaco mapo velja, dokler je naprava v ozjem krogu: kdor ga izgubi (odvzem, umik), jo potrebuje
    znova - nova seznanitev ali stikalo ne vrne domace mape brez nove privolitve."""
    surovo = ostalo.get("dom")
    ostane = {str(j): t for j, t in surovo.items() if _je_jedro(j) and OZJI_KROG <= set(naprave.get(str(j)) or ())} \
        if isinstance(surovo, dict) else {}
    if ostane:
        ostalo["dom"] = ostane
    else:
        ostalo.pop("dom", None)


def _zabelezi_dano(prej: Dict[str, Set[str]], naprave: Dict[str, Set[str]], ostalo: dict) -> None:
    """Ob vsakem zapisu: jedro, ki je dobilo novo zmoznost, dobi cas zdaj, jedro brez zmoznosti izgubi cas. Vrnitev
    naprave v krog po njem vzame samo pravice, dane pred umikom - nove privolitve ne (pregled 17, M2)."""
    dano = _dano_ob(ostalo)
    zdaj = time.time()
    for j, d in naprave.items():
        if set(d) - set(prej.get(j) or ()):
            dano[j] = zdaj
    dano = {j: t for j, t in dano.items() if naprave.get(j)}
    if dano:
        ostalo["dano_ob"] = dano
    else:
        ostalo.pop("dano_ob", None)


def _uveljavi_cakajoce(naprave: Dict[str, Set[str]], ostalo: dict) -> None:
    """Klicati pod _zaklep: cakajoci umiki gredo v vsak zapis, ne samo v ponovni poskus (pregled 17, M4)."""
    if not _cakajo_umik:
        return
    dano = _dano_ob(ostalo)
    for j, meja in _cakajo_umik.items():
        if naprave.get(j) and (meja is None or dano.get(j, 0.0) <= meja):
            naprave[j] = set()


def _dodaj_cakajoci(j: str, meja: Optional[float]) -> None:
    """Klicati pod _zaklep: brezpogojni umik ostane brezpogojen, pri dveh vrnitvah velja poznejsi cas umika."""
    if meja is None or (j in _cakajo_umik and _cakajo_umik[j] is None):
        _cakajo_umik[j] = None
    elif j in _cakajo_umik:
        _cakajo_umik[j] = max(float(meja), float(_cakajo_umik[j]))
    else:
        _cakajo_umik[j] = float(meja)


def _ponovi_umike() -> bool:
    """Klicati pod _zaklep: zapis umikov, ki se cakajo (_spremeni jih uveljavi). True, ce je bil zapis narejen."""
    if not _cakajo_umik:
        return False
    try:
        _spremeni(lambda naprave, zascita: None)
    except OSError:
        return False
    jedra = set(_cakajo_umik)
    if _na_disku_ni(jedra):
        for j in jedra:
            _cakajo_umik.pop(j, None)
    return True


def _nacrtuj_ponovitev() -> None:
    """Klicati pod _zaklep: ponovni zapis cakajocih umikov v svoji niti po UMIK_PONOVI_S - ne v poti branja (sme,
    straza, okno), ki je ob polnem disku vsakih 5 s stala na zapisu (pregled 17, M5)."""
    global _umik_casovnik
    if _umik_casovnik is not None or not _cakajo_umik:
        return
    t = threading.Timer(UMIK_PONOVI_S, _ponovi_v_ozadju)
    t.daemon = True
    t.name = "safeer-umik-ponovi"
    _umik_casovnik = t
    t.start()


def _ponovi_v_ozadju() -> None:
    global _umik_casovnik
    with _zaklep:
        _umik_casovnik = None
        _ponovi_umike()
        _nacrtuj_ponovitev()


def _na_disku_ni(jedra: Iterable[str]) -> bool:
    """Ali ta jedra na disku res nimajo nicesar (preverba po zapisu, ki zmanjsa pravice - pregled 11, N17)."""
    stanje, naprave, _z, _ob, _o = _z_diska(_pot())
    return stanje in ("ok", "pokvarjen") and not any(naprave.get(j) for j in jedra)


def _spremeni(sprememba: Callable[..., None],
              sprememba_ostalega: Optional[Callable[[dict], None]] = None,
              z_ostalim: bool = False) -> Dict[str, Set[str]]:
    """Branje-sprememba-zapis kot en korak, pod zaklepom programa IN datoteke. `sprememba(naprave, zascita)` spremeni
    oba na mestu (z `z_ostalim` dobi se polja zapisa: sprememba(naprave, zascita, ostalo)); `sprememba_ostalega(ostalo)`
    po zelji spremeni polja, ki jih zapis sicer samo prenasa (»zavrnjeno«).
    Polja, ki jih ta program ne pozna, ostanejo. Izhodisce je vedno stanje z DISKA - spremembe drugih programov ostanejo. Zapis »zascita« samo raste:
    kar ima ta program v pomnilniku, gre zraven (tudi kadar je zapis na disku pokvarjen ali ga je pisal starejsi
    program, ki zascite ne pozna). Ce zapisa se ni, je to prvi zagon z dovoljenji (podedovane naprave) - ce pa je
    dedovanje ze bilo (_dedovanje_opravljeno), nima dostopa nihce; pokvarjen zapis pomeni, da nima dostopa nihce (varna
    stran). Zapisa, ki ga ni mogoce PREBRATI, ne prepisemo: NapakaBranja. Ce se zapis med vsemi poskusi spreminja pod
    nami, ne zapisemo nicesar: NapakaZapisa. Vrne nove naprave in posodobi stanje v pomnilniku.

    Vsak zapis uveljavi cakajoce umike, zabelezi cas novih privolitev (dano_ob) in - zapis iz razlicice pred oznako
    dedovanja - podedovanim napravam vzame ozji krog; oznako zapise samo, ce je podedovane mogoce dolociti (pregled 17,
    M1: prej jo je zapisal vsak zapis, tudi ko kroga ni bilo mogoce prebrati)."""
    global _zapis, _zascita, _prebran_odtis, _prebrana_pot, _zascita_disk, _zapis_spodletel_ob, _zavrnjeno_disk
    global _migracija_caka_ob, _dom_disk
    with _zaklep:
        pot = _pot()
        migracija_caka, zmanjsana = False, set()
        try:
            # 0700: ime in obstoj zapisa ter zaklepa nista za druge uporabnike racunalnika (velja za novo mapo).
            os.makedirs(os.path.dirname(pot), mode=0o700, exist_ok=True)
            with _zaklenjen_zapis(pot):
                odtis = None
                for _poskus in range(NAJVEC_POSKUSOV_ZAPISA):
                    odtis_prej = _odtis_zapisa(pot)
                    stanje, naprave, zascita, ob, ostalo = _z_diska(pot)
                    migracija_caka, zmanjsana = False, set()
                    if stanje == "napaka":
                        raise NapakaBranja(5, "zapisa dovoljenj ni mogoce prebrati - ne prepisemo ga")
                    if stanje == "ni":
                        if _dedovanje_opravljeno(pot):
                            # Zapis je izginil po dedovanju: ne podedujemo znova (tudi naprav, ki jim je uporabnik
                            # dostop vzel) - nihce nima dostopa, uporabnik ga odpre znova.
                            print("[SafeerDostop] zapisa dovoljenj ni vec: dostopa nima nobena naprava", flush=True)
                            naprave, ob = {}, time.time()
                        else:
                            naprave, ob = _podedovane_naprave(), time.time()
                    elif stanje == "pokvarjen":
                        ob = time.time()
                    elif not _dedovanje_opravljeno(pot):
                        izrecna = _izrecna(ostalo)
                        podedovana = _podedovana_jedra_ali_none(naprave, izrecna)
                        if podedovana is None:
                            migracija_caka = True
                        else:
                            vse = set(VSE_ZMOZNOSTI)
                            zmanjsana = {j for j in podedovana if naprave.get(j) == vse and j not in izrecna}
                            for j in zmanjsana:
                                naprave[j] = set(PODEDOVANO)
                    if pot == _prebrana_pot:
                        zascita |= _zascita
                    _uveljavi_cakajoce(naprave, ostalo)
                    prej = {j: set(d) for j, d in naprave.items()}
                    if z_ostalim:
                        sprememba(naprave, zascita, ostalo)
                    else:
                        sprememba(naprave, zascita)
                    if sprememba_ostalega is not None:
                        sprememba_ostalega(ostalo)
                    _zabelezi_dano(prej, naprave, ostalo)
                    _pocisti_dom(naprave, ostalo)
                    # Zamenjamo samo, ce je zapis se tak, kot smo ga prebrali - vedno, tudi v zadnjem poskusu.
                    odtis = _na_disk(pot, naprave, zascita, ob, odtis_prej, ostalo=ostalo)
                    if odtis is not None:
                        break
                if odtis is None:
                    raise NapakaZapisa(11, "zapis dovoljenj se je ves cas spreminjal - sprememba ni zapisana")
            if not migracija_caka:
                _zabelezi_dedovanje(pot)
        except OSError:
            _zapis_spodletel_ob = time.monotonic()
            raise
        # Nova privolitev po umiku je v zapisu za umikom: umik zanjo ne caka vec (pregled 17, M4).
        for j in [j for j in _cakajo_umik if naprave.get(j)]:
            del _cakajo_umik[j]
        if zmanjsana:
            print("[SafeerDostop] %d podedovanih naprav brez ozjega kroga (upravljanje, Safeer Vnos, domaca mapa): "
                  "uporabnik ga odpre z eno privolitvijo v Safeer Linku" % len(zmanjsana), flush=True)
        if migracija_caka:
            _migracija_caka_ob = time.monotonic()
            naprave = _brez_ozjega(naprave, izrecna=_izrecna(ostalo))
        else:
            _migracija_caka_ob = None
        _zapis, _zascita, _prebran_odtis, _prebrana_pot = naprave, zascita, odtis, pot
        _zascita_disk, _zapis_spodletel_ob = set(zascita), None
        _zavrnjeno_disk = _zavrnjeno_iz(ostalo.get("zavrnjeno"))
        _dom_disk = _dom_iz(ostalo)
        return naprave


def _migracija_na_vrsti() -> bool:
    """Migracija starega zapisa caka na krog dlje od UMIK_PONOVI_S: _nalozen zapis prebere znova in jo ponovi."""
    return _migracija_caka_ob is not None and time.monotonic() - _migracija_caka_ob >= UMIK_PONOVI_S


def _nalozen() -> Dict[str, Set[str]]:
    """Zapis dovoljenj; znova prebran, ce ga je spremenil drug program na tem racunalniku (Control, brskalnik)."""
    global _zapis, _prebran_odtis, _prebrana_pot, _zascita, _zascita_disk, _zavrnjeno_disk, _dom_disk
    with _zaklep:
        pot = _pot()
        if pot != _prebrana_pot:
            # Drug zapis (preizkusi): kar smo vedeli za prejsnjega, zanj ne velja.
            _zascita, _zascita_disk, _zapis, _prebran_odtis, _prebrana_pot = set(), set(), None, None, pot
            _zavrnjeno_disk, _dom_disk = {}, set()
        try:
            odtis = _odtis_zapisa(pot)
        except OSError:
            # Zapis je, a ga ni mogoce niti pregledati: dostopa nima nihce, nicesar ne pisemo in si ne zapomnimo
            # (naslednji klic poskusi znova). To NI prvi zagon - podedovanega dostopa ni.
            _zapis, _prebran_odtis = None, None
            return {}
        if _zapis is not None and odtis == _prebran_odtis and not _migracija_na_vrsti():
            return _brez_cakajocih(_zapis)
        if odtis is None:
            # Zapisa (se) ni: prvi zagon z dovoljenji. Pod zaklepom datoteke - ce ga je medtem ustvaril drug program,
            # se samo prebere.
            try:
                return _brez_cakajocih(_spremeni(lambda naprave, zascita: None))
            except NapakaBranja:
                _zapis, _prebran_odtis = None, None     # zapis se je pojavil, a ni berljiv: nihce (glej zgoraj)
                return {}
            except OSError:
                # Zapisa ni in ustvariti se ga ne da (poln disk, mapa brez pravic): nihce, naslednji klic poskusi
                # znova. Prej je v tem programu veljal podedovan dostop - brez zapisa tudi brez oznake dedovanja,
                # torej ob vsaki taki napaki znova (sedmi pregled, 25. 10. 2026).
                _zapis, _prebran_odtis = None, None
                _zascita_disk = set()              # na disku ni nicesar: zapis »zascita« se vrne ob prvi priloznosti
                return {}
        stanje, naprave, zascita, _ob, ostalo = _z_diska(pot)
        if stanje == "napaka":
            _zapis, _prebran_odtis = None, None         # ni berljiv: nihce, brez pisanja, naslednjic znova
            return {}
        if stanje == "ok":
            _zascita = _zascita | zascita
            _zascita_disk = set(zascita)
            _zavrnjeno_disk = _zavrnjeno_iz(ostalo.get("zavrnjeno"))
            _dom_disk = _dom_iz(ostalo)
            if not _dedovanje_opravljeno(pot):
                # Zapis iz razlicice pred oznako dedovanja: ta je podedovanim napravam dala vse stiri (dpvz) - torej
                # tudi ozji krog (domaca mapa, Safeer Vnos) brez privolitve. Enkrat jih zmanjsamo na PODEDOVANO
                # (pregled 11, N1); kar je uporabnik po dedovanju spremenil (ni natanko dpvz), ostane.
                naprave, zapisano = _migriraj_podedovane(naprave, ostalo)
                if zapisano:
                    return _brez_cakajocih(_zapis or {})     # _spremeni je nastavil zapis in odtis
        else:
            # Pokvarjen zapis: nihce nima dostopa (varna stran), uporabnik ga odpre znova. Kar ta program ze ve o
            # napravah z dokazanim kljucem, OSTANE: pokvarjen zapis ne sme ugasniti pravila »samo zasciteno«.
            naprave = {}
            _zascita_disk, _dom_disk = set(), set()
        _zapis, _prebran_odtis = naprave, odtis
        return _brez_cakajocih(naprave)


def _brez_cakajocih(naprave: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """Zapis brez naprav, ki cakajo na zapis umika: v tem programu nimajo nicesar, dokler zapis ne uspe (ponavlja ga
    _nacrtuj_ponovitev v svoji niti - pot branja ne pise)."""
    if not _cakajo_umik:
        return naprave
    return {j: (set() if j in _cakajo_umik else d) for j, d in naprave.items()}


def _migriraj_podedovane(naprave: Dict[str, Set[str]],
                         ostalo: Optional[dict] = None) -> Tuple[Dict[str, Set[str]], bool]:
    """Klicati pod _zaklep iz _nalozen (zapis obstaja, oznake dedovanja se ni). Vrne (naprave, ali je zapisano z
    _spremeni, ki zmanjsa in zapise oznako). Ce podedovanih ni mogoce dolociti (krog ali kljuc ni berljiv) ali zapisa ni
    mogoce spremeniti, v tem programu nima ozjega kroga nobena naprava z vsemi stirimi (varna stran; programi in
    predvajalnik ostanejo), oznaka se ne zapise in migracija se ponovi po UMIK_PONOVI_S (pregled 17, M1). Naprav z
    izrecno privolitvijo v tej razlicici (_izrecna) ne zmanjsa nikoli (pregled 29, G2)."""
    global _migracija_caka_ob
    vse, izrecna = set(VSE_ZMOZNOSTI), _izrecna(ostalo or {})
    podedovana = _podedovana_jedra_ali_none(naprave, izrecna)
    if podedovana is not None and not any(naprave.get(j) == vse and j not in izrecna for j in podedovana):
        _zabelezi_dedovanje(_pot())
        _migracija_caka_ob = None
        return naprave, False
    if podedovana is not None:
        try:
            return _spremeni(lambda nove, zascita: None), True      # zmanjsa in zapise oznako
        except OSError:
            pass
    _migracija_caka_ob = time.monotonic()
    return _brez_ozjega(naprave, podedovana, izrecna), False

def jedro(device_id: str) -> str:
    def kljuc(i: str) -> Optional[str]:
        try:
            c = _krog().clan_za_id(i)
            return str(c.get("kljuc") or "") if c else None
        except Exception:  # noqa: BLE001
            return None
    return jedro_iz(device_id, kljuc, _id_iz_kljuca)


#: Predpona kljuca shrambe za oznako brez jedra (glej kljuc_shrambe).
BREZ_JEDRA = "brez-jedra:"


def kljuc_shrambe(device_id: str) -> str:
    """Kljuc, pod katerim shrambe (izrecno poslane datoteke, seznami prejemnikov oddaj) vodijo napravo: njeno jedro.
    Oznaka, pod katero je v krogu DRUG kljuc, jedra nima. Dobi kljuc, ki ne more biti enak jedru ali oznaki nobene
    druge naprave - tudi kadar je taka oznaka kar golo jedro prave naprave (`n-<16 hex>`): kar je shranjeno za pravo
    napravo, zanjo ne velja."""
    j = jedro(device_id)
    return j if j else BREZ_JEDRA + str(device_id or "")


def je_ta_naprava(device_id: str) -> bool:
    """Ali je id ta racunalnik sam (isti kljuc: Control, brskalnik, Safeer OS in pomozne identitete)."""
    if not device_id:
        return False
    nas = _lastni_kljuc()
    if not nas:
        return False
    try:
        return jedro(device_id) == _id_iz_kljuca(nas)
    except Exception:  # noqa: BLE001
        return False


def zmoznosti(device_id: str) -> Set[str]:
    """Kaj je napravi na tem racunalniku odprto."""
    if not device_id:
        return set()
    if je_ta_naprava(device_id):
        return set(VSE_ZMOZNOSTI)
    return set(_nalozen().get(jedro(device_id)) or ())


def v_ozjem_krogu(device_id: str) -> bool:
    """Ali je naprava v ozjem krogu tega racunalnika (OZJI_KROG: upravljanje in mape z eno izrecno privolitvijo). Samo
    taka vidi domaco mapo (link_datoteke, oznake dom:) - ne naprava, ki ima iz starejse razlicice samo »d« za izbrane
    mape (sedmi pregled, naloga 6, 25. 10. 2026)."""
    return bool(device_id) and OZJI_KROG <= zmoznosti(device_id)


def sme_domaco_mapo(device_id: str) -> bool:
    """Domaca mapa (oznake dom: in domaci del »vsega diska«, core/link_datoteke): ozji krog IN izrecna privolitev zanjo
    v tej razlicici (polje »dom«: stikalo ozjega kroga, »Dovoli« v obvestilu, »Dovoli domaco mapo« v oknu Link - vsako
    pove, da gre za domaco mapo). Zapis d+z iz prejsnje razlicice obdrzi datoteke in upravljanje, domaco mapo pa dobi
    sele z novo privolitvijo - ob prvem zagonu nove razlicice se ne podeli sama (vodja 25. 10. 2026: privolitev mora
    biti informirana). Napaka pomeni ne."""
    try:
        if not device_id:
            return False
        if je_ta_naprava(device_id):
            return True
        j = jedro(device_id)
        with _zaklep:
            naprave = _nalozen()
            return bool(j) and OZJI_KROG <= set(naprave.get(j) or ()) and j in _dom_disk
    except Exception:  # noqa: BLE001 - »ne vem« ni »da«
        return False


def sme(device_id: str, zahteva: str) -> bool:
    """Ali je napravi z to oznako odprto `zahteva` (za zeton streznika datotek, seznam naprav in oddaje sredisca -
    povsod, kjer ne presojamo posameznega sporocila)."""
    return zahteva == PROSTO or sme_z(zmoznosti(device_id), zahteva)


def zmoznosti_jedra(jedro_naprave: str) -> Set[str]:
    """Kaj je odprto napravi s tem jedrom (jedro pride iz PREVERJENEGA kljuca - core/link_e2e)."""
    if not jedro_naprave:
        return set()
    if jedro_naprave == lastno_jedro():
        return set(VSE_ZMOZNOSTI)
    return set(_nalozen().get(jedro_naprave) or ())


def zna_zascito(jedro_naprave: str) -> bool:
    """Ali je naprava s tem jedrom ze kdaj vzpostavila zascito s tem racunalnikom (ali pa je to ta racunalnik sam -
    njegovi programi jo znajo vedno, kadar je kriptografija na voljo)."""
    if not jedro_naprave:
        return False
    _nalozen()
    if jedro_naprave in _zascita:
        return True
    if jedro_naprave == lastno_jedro():
        try:
            from core import link_e2e
            return link_e2e.na_voljo()
        except Exception:  # noqa: BLE001
            return False
    return False


def zahteva_zascito(device_id: str) -> bool:
    """Ali od naprave s to oznako sprejmemo samo zascitena sporocila (ker vemo, da jih zna poslati) - in ji zascitene
    tipe tudi posiljamo samo zasciteno.

    Pri oznaki iz kljuca odloca jedro iz OBLIKE oznake, ne vnos v krogu: vnos s to oznako in DRUGIM kljucem (podtakne
    ga lahko clan ali sredisce, novejsi vnos krog sprejme) da prazno jedro in je prej zahtevo ugasnil - odgovori taki
    napravi so potem sli nezasciteni (drugi neodvisni pregled, 7. 10. 2026)."""
    device_id = str(device_id or "")
    if je_id_iz_kljuca(device_id) and zna_zascito(device_id[:DOLZINA_JEDRA]):
        return True
    return zna_zascito(jedro(device_id))


def zabelezi_zascito(jedro_naprave: str) -> None:
    """Z napravo je vzpostavljena preverjena seja: odslej od nje (in v njenem imenu) ne sprejmemo nezascitenega."""
    if not je_id_iz_kljuca(jedro_naprave) or len(jedro_naprave) != DOLZINA_JEDRA:
        return
    with _zaklep:
        _nalozen()
        if jedro_naprave == lastno_jedro():
            return
        nova = jedro_naprave not in _zascita
        if not nova:
            # V tem programu ze velja. Na disku je lahko ni vec: starejsi program na istem racunalniku polja »zascita«
            # ne pozna in ga ob svojem pisanju izpusti - po ponovnem zagonu bi ta program od naprave spet sprejel
            # nezascitene ukaze. Zato ga vrnemo (klic pride ob vsakem seznamu naprav); po neuspelem zapisu ne takoj znova.
            if jedro_naprave in _zascita_disk:
                return
            if _zapis_spodletel_ob is not None and time.monotonic() - _zapis_spodletel_ob < POPRAVILO_PO_NEUSPEHU_S:
                return
        _zascita.add(jedro_naprave)         # v tem programu velja takoj, tudi ce zapis ne uspe
        try:
            _spremeni(lambda naprave, zascita: zascita.add(jedro_naprave))
        except OSError:
            pass
        if nova:
            print("[SafeerLink] naprava %s…%s je dokazala kljuc: odslej od nje samo zasciteni ukazi"
                  % (jedro_naprave[:2], jedro_naprave[-4:]), flush=True)


def _sme_posiljatelj(device_id: str, zahteva: str, zascita: Optional[str], zascitljivo: bool) -> bool:
    if zahteva == PROSTO:
        return True
    if zascita:
        return sme_z(zmoznosti_jedra(str(zascita)), zahteva)
    if zascitljivo and zahteva_zascito(device_id):
        return False
    return sme_z(zmoznosti(device_id), zahteva)


def ujema_zascito(device_id: str, zascita: Optional[str]) -> bool:
    """Ali oznaka posiljatelja zascitenega sporocila pripada jedru njegovega PREVERJENEGA kljuca. Zascitenemu sporocilu
    oznako vpise seja od naprave do naprave (podpisana ponudba - core/link_hub._zasciteno_sporocilo), zato se mora
    ujemati; neujemanje pomeni napako ali poskus podtikanja - ukaz zavrnemo, sicer bi seja, ki jo ukaz zacne, veljala
    za drugo napravo (sedmi pregled, 25. 10. 2026). Oznaka iz kljuca da jedro iz svoje oblike (vnos z drugim kljucem
    pod njo pravega ne zasenci), stara oznaka prek kljuca v krogu. Brez zascite: True (nic za primerjati)."""
    if not zascita:
        return True
    d, j = str(device_id or ""), str(zascita)
    if je_id_iz_kljuca(d):
        return d[:DOLZINA_JEDRA] == j
    try:
        return bool(d) and jedro(d) == j
    except Exception:  # noqa: BLE001
        return False


def sme_dejanje(device_id: str, dejanje: str, zascita: Optional[str] = None) -> bool:
    """Ali sme posiljatelj izvesti ukaz. `zascita` je jedro iz preverjenega kljuca, kadar je sporocilo prislo zasciteno;
    brez nje velja oznaka, ki jo je vpisalo sredisce - a samo za napravo, ki zascite (se) ne zna."""
    return _sme_posiljatelj(device_id, zahteva_dejanja(dejanje), zascita, True)


def sme_sporocilo(device_id: str, tip: str, dejanje: str = "", zascita: Optional[str] = None) -> bool:
    """Kot sme_dejanje, za sporocila, ki niso ukaz. Pravilo »od naprave z zascito samo zasciteno« velja za tipe, ki jih
    naprave z zascito res posiljajo zascitene (link_e2e.ZASCITENI_TIPI); usklajevanje in zaslon gresta se po starem."""
    from core import link_e2e
    return _sme_posiljatelj(device_id, zahteva_sporocila(tip, dejanje), zascita, tip in link_e2e.ZASCITENI_TIPI)


def prejem_brez_vprasanja(device_id: str, zascita: Optional[str] = None) -> bool:
    """Ali datoteko te naprave (share.file) shranimo brez vprasanja: samo od naprave iz ozjega kroga TEGA racunalnika
    (kaksno dovoljenje tu, lastnik 18. 10. 2026). Od drugih v Safeer Linku najprej vprasamo; datoteka je prosta
    (zahteva_sporocila), zato je ne zavrnemo. Odlocitev ne podeli nobenega dostopa - samo izbere med »shrani« in
    »vprasaj«. share.file sestavi sredisce, ki je posiljatelja preverilo po zetonu (zascite od naprave do naprave ta
    tip nima), zato je oznaka posiljatelja tu ista kot v seznamu naprav; ob napaki branja zapisa vprasamo."""
    try:
        if zascita:
            return bool(zmoznosti_jedra(str(zascita)))
        return bool(zmoznosti(str(device_id or "")))
    except Exception:  # noqa: BLE001 - »ne vem« ni »da«
        return False


def nastavi(device_id: str, dano: Iterable[str]) -> bool:
    """Napravi zapise natanko `dano`; prazen nabor = brez dostopa (naprava samo pomaga pri povezavi). Ozjega kroga
    ne doda (to je nastavi_ozji_krog - stikalo uporabnika). Ce je napravi kaj vzeto, pocakajoce prosnje in obvestila
    izginejo in programi, ki so se javili (ob_odvzemu), takoj koncajo, kar zanjo tece."""
    return _nastavi(device_id, dano, ozji=False)


def _nastavi(device_id: str, dano: Iterable[str], ozji: bool) -> bool:
    if not device_id or je_ta_naprava(device_id):
        return False
    j = jedro(device_id)
    if not j:
        return False
    return _zapisi_jedru(j, iz_niza(v_niz(dano)), ozji=ozji)


def nastavi_ozji_krog(device_id: str, dano: Iterable[str]) -> bool:
    """Stikala v oknu Safeer Link kot nabor (izrecna privolitev uporabnika na TEM racunalniku): nabor z novo zmoznostjo
    da ozji krog (ozji_krog), prazen nabor ga vzame v celoti. Nabor, ki je del stanja naprave (izklop ali enak zapis
    drugic), samo vzame - nikoli ne doda (»pv« brez »p« je »v«, ne »dvz« s Safeer Vnos in domaco mapo; pregled 38, O1:
    prej je to veljalo samo za strogo podmnozico, enak zapis drugic je dal ozji krog). Okno Link poslje DEJANJE
    (preklopi_ozji_krog): iz nabora ni mogoce vedeti, kaj je uporabnik izklopil, ce okno kaze staro stanje.

    Domaca mapa (polje »dom«, sme_domaco_mapo) samo ob VKLOPU ozjega kroga - stikalo ozjega kroga pove, da jo
    vsebuje (link.js dostopZaslonOpis). Sprememba drugega stikala naprave, ki je ze v ozjem krogu, privolitve ne doda:
    naprava d+z iz prejsnje razlicice jo dobi samo z »Dovoli domaco mapo« ali z izklopom in vklopom ozjega kroga
    (pregled 29, G1: prej jo je zapisala vsaka sprememba stikal, tudi izklop »Programi«)."""
    return _nastavi(device_id, dano, ozji=True)


def preklopi_ozji_krog(device_id: str, zmoznost: str, vklop: bool) -> bool:
    """Stikalo v oknu Safeer Link: uporabnik je vklopil ali izklopil ENO zmoznost (pregled 38, O1). Jedro uporabi samo
    to razliko glede na stanje naprave v tem programu in na disku: ponovljen dogodek nima ucinka, okno s starim stanjem
    (po umiku iz kroga, po zapisu drugega programa) pa ne da nove pravice.
      - Izklop samo vzame, nikoli ne doda (ne ozjega kroga ne domace mape ne dano_ob). Izklop ozjega kroga (»z«) vzame
        ves dostop, izklop drugega stikala samo to zmoznost; naprava v ozjem krogu obdrzi d+z, naprava zunaj njega, ki
        ji ne ostane nobeno vidno stikalo, izgubi tudi »d« iz prejsnje razlicice (kot prej izklop vseh stikal).
      - Vklop da to zmoznost in ozji krog (ozji_krog), domaco mapo samo, ce ozjega kroga se ni imela (pregled 29, G1)."""
    if not isinstance(zmoznost, str) or zmoznost not in VSE_ZMOZNOSTI or not isinstance(vklop, bool):
        return False
    if not device_id or je_ta_naprava(device_id):
        return False
    j = jedro(device_id)
    if not j:
        return False
    return _zapisi_jedru(j, set(), ozji=True, dejanje=(zmoznost, vklop))


def _nabor_stikal(osnova: Set[str], zahtevano: Set[str], dejanje: Optional[Tuple[str, bool]]) -> Set[str]:
    """Nabor po stikalih okna (nastavi_ozji_krog z naborom, preklopi_ozji_krog z dejanjem). `osnova`: kar ima naprava v
    tem programu in na disku. Izklop in enak zapis vrneta podmnozico osnove - nikoli nove pravice (pregled 38, O1)."""
    if dejanje is not None:
        zmoznost, vklop = dejanje
        if vklop:
            return ozji_krog(osnova | {zmoznost})
        if zmoznost == ZASLON:
            return set()                            # izklop ozjega kroga vzame ves dostop
        nabor = osnova - {zmoznost}
    else:
        nabor = set(zahtevano)
        if not nabor or not nabor <= osnova:
            return ozji_krog(nabor)                 # nova zmoznost: ozji krog; prazen nabor ostane prazen
    if OZJI_KROG <= osnova:
        return nabor | OZJI_KROG                    # izklop drugega stikala ozjega kroga ne vzame
    if dejanje is None:
        # »d« (izbrane mape iz prejsnje razlicice) okno ne pokaze: ostane, dokler uporabnik ne izklopi vsega.
        return nabor | (osnova & {DATOTEKE})
    return nabor if nabor - {DATOTEKE} else set()   # nobeno vidno stikalo vec: kot izklop vseh (vzame tudi »d«)


def dovoli_domaco_mapo(device_id: str) -> bool:
    """»Dovoli domaco mapo« v oknu Safeer Link: napravi v ozjem krogu iz prejsnje razlicice (d+z brez polja »dom«)
    doda samo privolitev za domaco mapo; zmoznosti ostanejo, kot so. Naprava zunaj ozjega kroga je ne dobi."""
    if not device_id or je_ta_naprava(device_id):
        return False
    j = jedro(device_id)
    if not j:
        return False

    def sprememba(naprave: Dict[str, Set[str]], zascita: Set[str], ostalo: dict) -> None:
        if OZJI_KROG <= set(naprave.get(j) or ()):
            _dovoli_dom(j, ostalo)
    with _zaklep:
        _nalozen()
        try:
            _spremeni(sprememba, z_ostalim=True)
        except OSError:
            return False
        stanje, na_disku, _z, _ob, ostalo = _z_diska(_pot())
        return stanje == "ok" and OZJI_KROG <= set(na_disku.get(j) or ()) and j in _dom_iz(ostalo)


def _zapisi_jedru(j: str, zahtevano: Set[str], ozji: bool = False,
                  dejanje: Optional[Tuple[str, bool]] = None) -> bool:
    """Napravi zapise `zahtevano` (`ozji`: pravilo stikal okna, glej nastavi_ozji_krog; `dejanje`: eno stikalo, glej
    preklopi_ozji_krog). True (»Shranjeno«) samo, ce je zapisano na disku IN v tem programu res velja (pregled 17, M10;
    pregled 29, G2)."""
    prej: List[Optional[Set[str]]] = [None]
    # Zadnji izracun spremembe: izvede se ob vsakem poskusu zapisa, vedno iz stanja z diska.
    izid: dict = {"nabor": set(zahtevano), "dom": False}
    with _zaklep:
        # Kar ima naprava ta hip v tem programu - in kar vidi uporabnik v oknu: cakajoci umik in cakajoca migracija sta
        # ze upostevana. Prvi zagon (podedovane naprave) se zgodi pred prvo spremembo.
        ucinkovito = set(_nalozen().get(j) or ())

        def sprememba(naprave: Dict[str, Set[str]], zascita: Set[str], ostalo: dict) -> None:
            trenutno = set(naprave.get(j) or ())
            if prej[0] is None:
                prej[0] = set(trenutno)
            if ozji:
                # Stikala: izhodisce je stanje v programu IN na disku - kar je drug program medtem vzel, izklop ali vklop
                # drugega stikala ne vrne (pregled 38, O1).
                osnova = ucinkovito & trenutno
                nabor = _nabor_stikal(osnova, set(zahtevano), dejanje)
            else:
                osnova, nabor = ucinkovito, set(zahtevano)
            # Domaca mapa samo ob VKLOPU ozjega kroga (pregled 29, G1). Izklop je ne doda nikoli: nabor <= osnova.
            dom = ozji and OZJI_KROG <= nabor and not OZJI_KROG <= ucinkovito
            izid["nabor"], izid["dom"] = set(nabor), dom
            naprave[j] = set(nabor)
            if dom:
                _dovoli_dom(j, ostalo)
            if nabor - osnova:
                # Nova privolitev glede na to, kar je naprava imela v tem programu - tudi ce je zapis na disku ze imel
                # vse stiri iz prejsnje razlicice: izrecna (_izrecna), migracija je ne zmanjsa. Izklop je nima.
                dano = _dano_ob(ostalo)
                dano[j] = time.time()
                ostalo["dano_ob"] = dano
        ok = False
        for _poskus in range(2):
            try:
                v_programu = _spremeni(sprememba, z_ostalim=True)
            except OSError:
                break                   # zapisa ni mogoce prebrati ali zapisati: spremembe ni (klicatelj to pove)
            nabor, dom = set(izid["nabor"]), bool(izid["dom"])
            # Zapis preverimo na disku: starejsi program (brez preverbe zapisa) ga lahko takoj povozi s starim stanjem
            # (pregled 11, N17) - potem se enkrat, sicer napaka, ki jo uporabnik vidi. Tudi nova privolitev: »Shranjeno«
            # samo, ce je res zapisana (pregled 17, M10).
            stanje, na_disku, _z, _ob, _o = _z_diska(_pot())
            if stanje == "ok":
                ok = set(na_disku.get(j) or ()) == nabor and (not dom or j in _dom_iz(_o))
            else:
                ok = not nabor and stanje in ("ni", "pokvarjen")     # brez zapisa nima nihce nicesar
            # Zapisano mora tudi veljati: cakajoca migracija ali umik tega zapisa v programu ne smeta zmanjsati, okno pa
            # javiti »Shranjeno« (pregled 29, G2).
            ok = ok and set(_brez_cakajocih(v_programu).get(j) or ()) == nabor
            if ok:
                break
    if prej[0] is not None and prej[0] - set(izid["nabor"]):
        _po_odvzemu(j)
    return ok


def ob_umiku_iz_kroga(jedra: Iterable[str], vracajo: Optional[Dict[str, float]] = None) -> None:
    """Naprave so umaknjene iz Safeer Linka (krog zaupanja, core/link_krog): ozji krog jim takoj vzame vse. Nova
    seznanitev z istim kljucem tako ne vrne nicesar brez nove privolitve (sedmi pregled, 25. 10. 2026: vnos v
    dostop.json je prej ostal in z njim d+z).

    `vracajo` (jedro -> cas umika): naprave, ki se vracajo po umiku. Vzame se samo, kar je bilo dano PRED umikom
    (dano_ob): privolitev po vrnitvi ostane, tudi ce zapis o vrnitvi pride znova ali iz drugega programa tega
    racunalnika z zastarelim krogom (pregled 17, M2: prej je vsaka taka zdruzitev izbrisala novo privolitev)."""
    umaknjena = {str(x) for x in (jedra or ())}
    meje: Dict[str, float] = {}
    for x, t in (vracajo or {}).items():
        try:
            meje[str(x)] = float(t)
        except (TypeError, ValueError):
            umaknjena.add(str(x))       # cas umika ni berljiv: kot umik (varna stran)
    vhod = umaknjena | set(meje)
    nas = lastno_jedro()
    vsa = sorted(j for j in vhod if _je_jedro(j) and j != nas)
    for j in sorted(vhod - set(vsa) - {nas}):
        print("[SafeerDostop] umik iz kroga: oznaka ni jedro, prezrta (%d znakov)" % len(j), flush=True)
    if not vsa:
        return
    pogojno = {j: meje[j] for j in vsa if j in meje and j not in umaknjena}
    vzeto: Set[str] = set()
    caka: Set[str] = set()
    with _zaklep:
        try:
            zapis = _nalozen()
            berljiv = _zapis is not None
        except Exception:  # noqa: BLE001
            zapis, berljiv = {}, False
        # Zapisa ni mogoce prebrati: ne vemo, kdo ima kaj - umik caka za vse (pregled 17, M5; prej ni cakal nihce in
        # umaknjena naprava je ob ponovnem branju spet imela d+z).
        imajo = {j for j in vsa if zapis.get(j)} if berljiv else set(vsa)
        if imajo:
            # En zapis za vse (odjava z desetimi napravami ni deset zapisov - pregled 11, N15).
            def sprememba(naprave: Dict[str, Set[str]], zascita: Set[str], ostalo: dict) -> None:
                dano = _dano_ob(ostalo)
                for j in imajo:
                    if naprave.get(j) and (j not in pogojno or dano.get(j, 0.0) <= pogojno[j]):
                        naprave[j] = set()
                        vzeto.add(j)
            try:
                _spremeni(sprememba, z_ostalim=True)
                zapisano = _na_disku_ni(vzeto)
            except OSError:
                zapisano = False
            if not zapisano:
                # V tem programu nimajo nicesar takoj; zapis ponavlja casovnik (_nacrtuj_ponovitev). Pregled 11, N3.
                caka = set(imajo)
                for j in caka:
                    _dodaj_cakajoci(j, pogojno.get(j))
                _nacrtuj_ponovitev()
                print("[SafeerDostop] umik iz kroga: zapisa dovoljenj ni bilo mogoce spremeniti - ponovimo", flush=True)
    # Naprava, ki se vraca in ima samo privolitev po umiku, ni izgubila nicesar: njene seje in prosnje ostanejo.
    for j in sorted((set(vsa) - set(pogojno)) | vzeto | caka):
        _po_odvzemu(j)

#: Programi, ki ob odvzemu dostopa takoj koncajo, kar za napravo tece (Safeer Link: seja zaslona, zetoni datotek,
#: Teamwork). Sibke reference: preizkusi in ponovno ustvarjeni predmeti ne ostanejo v seznamu.
_ob_odvzemu: List[weakref.ref] = []


def ob_odvzemu(klic: Callable[[str], None]) -> None:
    """Javi `klic(jedro)`: poklican ob vsakem zmanjsanju dostopa naprave (katerakoli nit) - iz okna, iz kroga ali iz
    drugega programa tega procesa."""
    ref = weakref.WeakMethod(klic) if hasattr(klic, "__self__") else weakref.ref(klic)
    with _zaklep:
        _ob_odvzemu[:] = [r for r in _ob_odvzemu if r() is not None and r() != klic]
        _ob_odvzemu.append(ref)


def _po_odvzemu(j: str) -> None:
    """Napravi je bilo kaj vzeto: cakajoce prosnje in njihovo obvestilo izginejo (stari »Dovoli« ne vrne dostopa, ki ga
    je uporabnik pravkar vzel), programi koncajo, kar zanjo tece."""
    with _zaklep:
        for k in [k for k, p in _prosnje.items() if p.get("jedro") == j]:
            _prosnje.pop(k, None)
        for k in [k for k in _zadnji_poziv if k.partition("|")[0] == j]:
            _zadnji_poziv.pop(k, None)
        _zetoni_gumbov.pop(j, None)
        klici = [r() for r in _ob_odvzemu]
    _osvezi_prikaz(j)
    for klic in klici:
        if klic is None:
            continue
        try:
            klic(j)
        except Exception as e:  # noqa: BLE001 - drugi programi morajo dobiti svoj klic
            print(f"[SafeerDostop] ob odvzemu: {e}", flush=True)


def naprave_z(zahteva: str) -> Set[str]:
    """Jedra naprav, ki jim je tu odprto `zahteva` (crka zmoznosti ali VSE = ozji krog)."""
    return {j for j, dano in _nalozen().items() if sme_z(dano, zahteva)}


def vsi() -> Dict[str, str]:
    """Ves zapis (jedro -> crke) za vmesnik."""
    return {j: v_niz(d) for j, d in _nalozen().items()}


def lastno_jedro() -> str:
    """Jedro tega racunalnika (prazno, dokler nima kljuca)."""
    nas = _lastni_kljuc()
    if not nas:
        return ""
    try:
        return _id_iz_kljuca(nas)
    except Exception:  # noqa: BLE001
        return ""


def prejemniki(navedeni, posiljatelj: str, zahteva: str = VSE) -> Set[str]:
    """Komu sme sredisce na tem racunalniku posredovati sporocilo brez cilja (stanje predvajanja, usklajevanje).

    Izvor jih navede sam (polje `allow`: jedra naprav, ki jim je pri NJEM odprto). Izvor brez polja (starejsa
    razlicica) ne more povedati, komu zaupa: ce je sam v ozjem krogu TEGA racunalnika, gre sporocilo ozjemu krogu tega
    racunalnika (naprave istega uporabnika delajo naprej, dokler niso posodobljene); sicer nikomur. Posiljatelj sam je
    vedno zraven (njegovi drugi programi na isti napravi)."""
    if isinstance(navedeni, list):
        izid = {str(x) for x in navedeni if isinstance(x, str)}
    elif sme(posiljatelj, zahteva):
        izid = naprave_z(zahteva)
        nas = lastno_jedro()
        if nas:
            izid.add(nas)
    else:
        izid = set()
    izid.add(kljuc_shrambe(posiljatelj))
    izid.discard("")
    izid.discard(BREZ_JEDRA)
    return izid


_zabelezeno: Dict[str, List[float]] = {}


def zabelezi(posiljatelj: str, kaj: str, zdaj: Optional[float] = None) -> None:
    """Zavrnitev v dnevnik - najvec ena vrstica na minuto za isto napravo in isto stvar (stara razlicica na drugi
    strani sprasuje vsakih nekaj sekund), s stevilom vmesnih ponovitev."""
    zdaj = time.monotonic() if zdaj is None else zdaj
    kljuc = f"{posiljatelj}|{kaj}"
    with _zaklep:
        vnos = _zabelezeno.get(kljuc)
        if vnos is not None and zdaj - vnos[0] < 60.0:
            vnos[1] += 1
            return
        ponovitev = int(vnos[1]) if vnos is not None else 0
        _zabelezeno[kljuc] = [zdaj, 0]
        if len(_zabelezeno) > 256:
            for k in sorted(_zabelezeno, key=lambda x: _zabelezeno[x][0])[:64]:
                _zabelezeno.pop(k, None)
    dodatek = f" (+{ponovitev} enakih)" if ponovitev else ""
    print(f"[SafeerDostop] Zavrnjeno: {posiljatelj or 'neznana naprava'} nima dostopa za {kaj}{dodatek}")


# ---------------------------------------------------------------------- prosnje za dostop (odobri ta racunalnik)
#
# Lastnik, 14. 10. 2026: naprava (npr. telefon druzinskega clana, dodan v Safeer Link), ki zeli dostop do tega
# racunalnika, ga dobi samo, ce ga odobri uporabnik NA TEM racunalniku - zascita pred napadalcem. Prej je naprava brez
# dostopa dobila samo zavrnitev; uporabnik jo je moral sam poiskati v nastavitvah.
#
# Ko racunalnik zavrne ZASCITENO sporocilo (posiljatelja dokazuje kljuc - nezascitenemu »sender« vpise sredisce in ga
# je mogoce ponarediti), ker naprava nima ENE zmoznosti (d/p/v/z - ne »*«), in je naprava clan kroga tega
# racunalnika, si zapomni prosnjo {jedro, ime, zmoznost, cas} in program z obvestili (Safeer Control) pokaze obvestilo
# z gumboma Dovoli / Zavrni. Ime naprave je iz kroga TEGA racunalnika, nikoli iz besedila sporocila. Dovoli doda samo
# tisto eno crko; odobri se lahko samo odprta prosnja in samo s klikom uporabnika (dejanje aplikacije, glej
# safeer_control) - nic v prispelem sporocilu je ne more odobriti. Zavrni za 24 ur utisa isto prosnjo (zapis
# »zavrnjeno« v dostop.json, da velja tudi po ponovnem zagonu). Ista prosnja najvec enkrat na 10 minut. Stevila
# odprtih prosenj in zavrnitev ne omejuje stevilka (lastnik, 18. 10. 2026: prej 5 odprtih in 256 zavrnitev - v vecjem
# krogu so prosnje izpadale, preden jih je uporabnik videl): prosnjo sprozi samo clan kroga, vsaka naprava najvec eno
# na crko (d/p/v/z), zato jih je najvec stirikrat toliko, kolikor je clanov; izpadejo po ZAVRNITEV_VELJA_S.
#
# Napravi gre v odgovoru (ob nespremenjeni stari obliki zavrnitve) se "access_request": "pending" | "declined" | "none"
# in "capability": crka (isti protokol kot Android).
#
# Ena naprava = eno obvestilo (lastnik, 15. 10. 2026: telefon je ob odpiranju racunalnika hkrati zaprosil za
# predvajalnik, zaslon in programe - racunalnik je pokazal tri obvestila zapored). Prosnje se se vedno vodijo vsaka
# zase (pogostost, 24 ur, najvec odprtih), obvestilo pa je eno na napravo (id po jedru) in nasteje vse njene odprte
# prosnje; nova prosnja iste naprave ga zamenja. Prikaz je odlozen za ZDRUZI_S (ZdruzenPrikaz), da prosnje, ki
# pridejo skoraj hkrati, ne utripnejo trikrat. »Dovoli« odobri natanko nastete crke - in od teh samo tiste, ki se
# cakajo; »Zavrni« zavrne vse nastete za 24 ur.

PROSNJA_PONOVNO_S = 600.0
ZAVRNITEV_VELJA_S = 86400.0
NAJVEC_IMENA = 60
#: Prosnje iste naprave, ki pridejo v tem casu, gredo v eno obvestilo (ZdruzenPrikaz).
ZDRUZI_S = 2.0
PROSNJA_ODPRTA, PROSNJA_ZAVRNJENA, PROSNJA_NI = "pending", "declined", "none"

#: Odprte prosnje po vrsti nastanka: "<jedro>|<crka>" -> {"jedro", "ime", "zmoznost", "cas"}.
_prosnje: "OrderedDict[str, dict]" = OrderedDict()
#: Kdaj (time.time) je bil uporabnik nazadnje vprasan za isto prosnjo.
_zadnji_poziv: Dict[str, float] = {}
#: Zavrnitve v tem programu (na disku jih lahko izbrise starejsi program, ki polja »zavrnjeno« ne pozna).
_zavrnjeno: Dict[str, float] = {}
#: Enkratni zeton gumbov zadnjega obvestila naprave (jedro -> zeton): dejanje »Dovoli«/»Zavrni« velja samo z njim.
#: Dejanja aplikacije so na vodilu seje (org.gtk.Actions) dosegljiva vsakemu procesu - brez zetona bi jih lahko
#: sprozil kdorkoli, ne samo klik v obvestilu (sedmi pregled, 25. 10. 2026).
_zetoni_gumbov: Dict[str, str] = {}
#: Prikaz obvestila (nastavi ga program z obvestili - Safeer Control); brez njega prosnje ni mogoce pokazati.
_prikaz: Optional[Callable[[dict], None]] = None
_umik: Optional[Callable[[str], None]] = None


def kljuc_prosnje(jedro_naprave: str, zmoznost: str) -> str:
    return f"{jedro_naprave}|{zmoznost}"


def kljuc_skupine(jedro_naprave: str, zmoznosti: str) -> str:
    """Parameter gumbov obvestila: "<jedro>|<crke>" (npr. "n-…|vzp")."""
    return f"{jedro_naprave}|{zmoznosti}"


def _je_jedro(j: object) -> bool:
    return isinstance(j, str) and len(j) == DOLZINA_JEDRA and je_id_iz_kljuca(j)


def razcleni_kljuc_prosnje(kljuc: str) -> Optional[Tuple[str, str]]:
    """"<jedro>|<crka>" -> (jedro, crka) ali None, ce ni prave oblike."""
    if not isinstance(kljuc, str):
        return None
    j, locilo, z = kljuc.partition("|")
    if not locilo or not _je_jedro(j) or z not in VSE_ZMOZNOSTI:
        return None
    return j, z


def razcleni_kljuc_skupine(kljuc: str) -> Optional[Tuple[str, str]]:
    """"<jedro>|<crke>" -> (jedro, crke) ali None. Crke: 1 do 4 razlicne iz VSE_ZMOZNOSTI (ne »*«); en sam znak je
    stara oblika parametra (ena prosnja)."""
    if not isinstance(kljuc, str):
        return None
    j, locilo, crke = kljuc.partition("|")
    if (not locilo or not _je_jedro(j) or not crke or len(crke) > len(VSE_ZMOZNOSTI)
            or len(set(crke)) != len(crke) or any(c not in VSE_ZMOZNOSTI for c in crke)):
        return None
    return j, crke


def _zavrnjeno_iz(surovo: object) -> Dict[str, float]:
    """Polje »zavrnjeno« z diska; vnosi napacne oblike se izpustijo."""
    if not isinstance(surovo, dict):
        return {}
    izid: Dict[str, float] = {}
    for k, v in surovo.items():
        if razcleni_kljuc_prosnje(k) is None or isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            continue
        izid[k] = float(v)
    return izid


def cisto_ime(ime: object) -> str:
    """Ime naprave za obvestilo: brez nadzornih znakov (prelomi, smer pisave), strnjeni presledki, najvec 60 znakov."""
    s = "".join(c if c.isprintable() else " " for c in str(ime or ""))
    return " ".join(s.split())[:NAJVEC_IMENA].strip()


def _ime_clana(jedro_naprave: str) -> Optional[str]:
    """Ime naprave s tem jedrom iz kroga TEGA racunalnika; None, ce naprava ni clan kroga. Prednost ima vnos, katerega
    oznaka je jedro samo (naprava), pred sorodnimi programi iste naprave."""
    try:
        k = _krog()
        with k._zaklep:
            clani = [dict(c) for c in k.clani.values() if k._veljaven(c)]
    except Exception:  # noqa: BLE001 - brez kroga ni clanov
        return None
    najdeno: Optional[str] = None
    for c in clani:
        kljuc = str(c.get("kljuc") or "")
        if not kljuc:
            continue
        try:
            if _id_iz_kljuca(kljuc) != jedro_naprave:
                continue
        except Exception:  # noqa: BLE001 - pokvarjen vnos preskocimo
            continue
        ime = cisto_ime(c.get("ime"))
        if str(c.get("id") or "") == jedro_naprave and ime:
            return ime
        if not najdeno:
            najdeno = ime
    if najdeno is None:
        return None
    return najdeno or jedro_naprave


def _zavrnjeno_ob(kljuc: str) -> float:
    return max(_zavrnjeno.get(kljuc, 0.0), _zavrnjeno_disk.get(kljuc, 0.0))


def _pocisti_prosnje(zdaj: float) -> None:
    """Pocisti stare vnose. Razlika je absolutna: ura, ki skoci nazaj, vnosa ne ohrani za vedno."""
    for k in [k for k, p in _prosnje.items() if abs(zdaj - float(p.get("cas") or 0.0)) >= ZAVRNITEV_VELJA_S]:
        _prosnje.pop(k, None)
    for k in [k for k, t in _zadnji_poziv.items() if abs(zdaj - t) >= PROSNJA_PONOVNO_S]:
        _zadnji_poziv.pop(k, None)
    for k in [k for k, t in _zavrnjeno.items() if abs(zdaj - t) >= ZAVRNITEV_VELJA_S]:
        _zavrnjeno.pop(k, None)


def nastavi_prikaz(pokazi: Optional[Callable[[dict], None]], umakni: Optional[Callable[[str], None]] = None) -> None:
    """Program z obvestili (Safeer Control) se javi: `pokazi(prosnja)` pokaze obvestilo z Dovoli/Zavrni (klic pride
    iz katerekoli niti), `umakni(kljuc_prosnje)` ga umakne, ko prosnja izpade. None: prosenj ta program ne kaze."""
    global _prikaz, _umik
    with _zaklep:
        _prikaz, _umik = pokazi, umakni


def prosnja_ob_zavrnitvi(device_id: str, zahteva: str, zascita: Optional[str] = None,
                         zdaj: Optional[float] = None, v_ozadju: bool = False) -> Tuple[str, str]:
    """Racunalnik je zahtevo naprave pravkar zavrnil. Ce je sporocilo prislo ZASCITENO (posiljatelja dokazuje kljuc),
    napravi manjka ena zmoznost in je clan kroga, uporabnika tu vprasa (obvestilo). Vrne (access_request, capability)
    za odgovor napravi. Nikoli ne odpre nicesar.

    Samo zasciteno (isto pravilo kot Android): polje »sender« nezascitenega sporocila vpise sredisce, zato bi lahko
    ponarejeno sporocilo uporabniku pokazalo »<druzinski clan> prosi za dostop« in ga pripravilo do odobritve tuji
    napravi. Nezascitena sporocila (tudi starejsih naprav, ki zascite ne znajo) dobijo "none" in obvestila ni.

    `v_ozadju` (lastnik, 15. 10. 2026): zahteva, ki je naprava ni poslala na uporabnikov ukaz (npr. predpomnjenje
    seznama programov na domacem zaslonu telefona), obvestila NE odpre - uporabnik ni nic zahteval in ga to zmede.
    Napravi povemo le, ali prosnja ze caka ali je zavrnjena. Polje lahko obvestilo samo prepreci, nikoli ne odpre
    nicesar."""
    zdaj = time.time() if zdaj is None else zdaj
    if zahteva not in VSE_ZMOZNOSTI or not zascita:
        return PROSNJA_NI, zahteva
    try:
        j = str(zascita)                 # jedro iz PREVERJENEGA kljuca (core/link_e2e), ne oznaka iz sredisca
        if not _je_jedro(j) or j == lastno_jedro():
            return PROSNJA_NI, zahteva
        if zahteva in zmoznosti_jedra(j):
            return PROSNJA_NI, zahteva   # zavrnjeno iz drugega razloga
        kljuc = kljuc_prosnje(j, zahteva)
        if abs(zdaj - _zavrnjeno_ob(kljuc)) < ZAVRNITEV_VELJA_S:
            return PROSNJA_ZAVRNJENA, zahteva
        ime = _ime_clana(j)
        if ime is None:
            return PROSNJA_NI, zahteva   # ni clan kroga tega racunalnika
    except Exception:  # noqa: BLE001 - napaka nikoli ne sprozi vprasanja
        return PROSNJA_NI, zahteva
    if v_ozadju:
        with _zaklep:
            _pocisti_prosnje(zdaj)
            return (PROSNJA_ODPRTA if kljuc in _prosnje else PROSNJA_NI), zahteva
    with _zaklep:
        pokazi, umakni = _prikaz, _umik
        if pokazi is None:
            return PROSNJA_NI, zahteva
        _pocisti_prosnje(zdaj)
        zadnji = _zadnji_poziv.get(kljuc)
        if zadnji is not None and abs(zdaj - zadnji) < PROSNJA_PONOVNO_S:
            return (PROSNJA_ODPRTA if kljuc in _prosnje else PROSNJA_NI), zahteva
        prosnja = {"jedro": j, "ime": ime, "zmoznost": zahteva, "cas": zdaj}
        _prosnje.pop(kljuc, None)
        _prosnje[kljuc] = prosnja
        _zadnji_poziv[kljuc] = zdaj
        skupina = _skupina(j)
    try:
        pokazi(skupina)
    except Exception as e:  # noqa: BLE001 - obvestila ni bilo: napravi povemo, da prosnje ni
        with _zaklep:
            if _prosnje.get(kljuc) is prosnja:
                _prosnje.pop(kljuc, None)
        print(f"[SafeerDostop] Prosnje ni bilo mogoce pokazati: {e}")
        return PROSNJA_NI, zahteva
    print(f"[SafeerDostop] Prosnja za dostop: {j[:2]}…{j[-4:]} ({zahteva}) caka na odobritev na tem racunalniku",
          flush=True)
    return PROSNJA_ODPRTA, zahteva


def prosnja_ob_zavrnitvi_sporocila(device_id: str, tip: str, dejanje: str = "",
                                   zascita: Optional[str] = None) -> Tuple[str, str]:
    """Kot prosnja_ob_zavrnitvi, za sporocila, ki niso ukaz (cast.url). Zasciteno lahko pride samo tip iz
    link_e2e.ZASCITENI_TIPI; share.screen ni med njimi, zato zanj prosnje ni (sredisce zasciten share.screen zavrze)."""
    return prosnja_ob_zavrnitvi(device_id, zahteva_sporocila(tip, dejanje), zascita)


def z_prosnjo(odgovor: dict, stanje: str, zmoznost: str) -> dict:
    """Zavrnitev z dodanim stanjem prosnje. Obstojeca polja ostanejo, kot so (starejse naprave jih berejo); seznami
    dobijo polji tudi v "data"."""
    izid = dict(odgovor)
    izid["access_request"] = stanje
    izid["capability"] = zmoznost
    if isinstance(izid.get("data"), dict):
        izid["data"] = dict(izid["data"], access_request=stanje, capability=zmoznost)
    return izid


def odprte_prosnje() -> List[dict]:
    with _zaklep:
        _pocisti_prosnje(time.time())
        return [dict(p) for p in _prosnje.values()]


def _skupina(jedro_naprave: str) -> Optional[dict]:
    """Odprte prosnje ene naprave kot eno obvestilo (klicati pod _zaklep): {"jedro", "ime", "zmoznosti" (crke po
    vrsti prihoda), "zmoznost" (prva - za starejse bralce), "cas" (najnovejsa)}. None, ce naprava nima odprte prosnje."""
    odprte = [p for p in _prosnje.values() if p.get("jedro") == jedro_naprave]
    if not odprte:
        return None
    zadnja = odprte[-1]
    crke = "".join(str(p["zmoznost"]) for p in odprte)
    return {"jedro": jedro_naprave, "ime": zadnja.get("ime"), "zmoznosti": crke, "zmoznost": crke[0],
            "cas": zadnja.get("cas")}


def skupina_prosenj(jedro_naprave: str) -> Optional[dict]:
    """Kar mora zdaj pisati v obvestilu naprave (glej _skupina); None = obvestila ni vec."""
    with _zaklep:
        _pocisti_prosnje(time.time())
        return _skupina(str(jedro_naprave or ""))


def _osvezi_prikaz(jedro_naprave: str) -> None:
    """Obvestilo naprave po spremembi njenih prosenj: s preostalimi crkami ali umik, ce ni nobene vec."""
    with _zaklep:
        skupina = _skupina(jedro_naprave)
        pokazi, umakni = _prikaz, _umik
    try:
        if skupina is not None and pokazi is not None:
            pokazi(skupina)
        elif skupina is None and umakni is not None:
            umakni(jedro_naprave)
    except Exception as e:  # noqa: BLE001
        print(f"[SafeerDostop] Obvestila prosnje ni bilo mogoce osveziti: {e}")


def opusti_prosnje(jedro_naprave: str) -> None:
    """Obvestila naprave ni bilo mogoce pokazati: njene prosnje niso vec odprte (naprava dobi "none", nic se ne
    zavrne). Uporabi ZdruzenPrikaz, ki obvestilo pokaze z zamikom."""
    with _zaklep:
        for k in [k for k, p in _prosnje.items() if p.get("jedro") == jedro_naprave]:
            _prosnje.pop(k, None)


def dodaj_zmoznosti(device_id: str, zmoznosti: Iterable[str]) -> bool:
    """Napravi doda NATANKO nastete zmoznosti k tistim, ki jih ze ima - z enim zapisom (branje-sprememba-zapis pod
    zaklepom, kot nastavi). Vse ali nic: neznana crka ali »*« zavrne celoto. Ozjega kroga ne doda (samo odobri_prosnjo
    - »Dovoli« uporabnika)."""
    return _dodaj_zmoznosti(device_id, zmoznosti, ozji=False)


def _dodaj_zmoznosti(device_id: str, zmoznosti: Iterable[str], ozji: bool) -> bool:
    dodaj = set(zmoznosti or ())
    if not dodaj or not dodaj <= VSE_ZMOZNOSTI or not device_id or je_ta_naprava(device_id):
        return False
    j = jedro(device_id)
    if not j:
        return False
    kljuci = {kljuc_prosnje(j, z) for z in dodaj}

    def sprememba(naprave: Dict[str, Set[str]], zascita: Set[str]) -> None:
        novo = set(naprave.get(j) or ()) | dodaj
        naprave[j] = ozji_krog(novo) if ozji else novo

    def sprememba_ostalega(ostalo: dict) -> None:
        if "zavrnjeno" in ostalo:
            z = _zavrnjeno_iz(ostalo.get("zavrnjeno"))
            for k in kljuci:
                z.pop(k, None)
            ostalo["zavrnjeno"] = z
        if ozji:
            # »Dovoli« v obvestilu: telo obvestila pove, da naprava dobi tudi domaco mapo (telo_obvestila).
            _dovoli_dom(j, ostalo)
    with _zaklep:
        _nalozen()
        try:
            _spremeni(sprememba, sprememba_ostalega)
        except OSError:
            return False
        for k in kljuci:
            _zavrnjeno.pop(k, None)
    return True


def dodaj_zmoznost(device_id: str, zmoznost: str) -> bool:
    """Napravi doda ENO zmoznost (glej dodaj_zmoznosti)."""
    if zmoznost not in VSE_ZMOZNOSTI:
        return False
    return dodaj_zmoznosti(device_id, (zmoznost,))


def odobri_prosnjo(jedro_naprave: str, zmoznosti: str) -> bool:
    """Uporabnik je na TEM racunalniku pritisnil Dovoli. `zmoznosti` so crke, nastete v obvestilu (ena ali vec);
    odobrijo se samo tiste, za katere prosnja res caka - nic drugega. True, ce je bila odobrena vsaj ena."""
    par = razcleni_kljuc_skupine(kljuc_skupine(str(jedro_naprave or ""), str(zmoznosti or "")))
    if par is None:
        return False
    j, crke = par
    with _zaklep:
        _pocisti_prosnje(time.time())
        odprte = "".join(c for c in crke if kljuc_prosnje(j, c) in _prosnje)
    if not odprte:
        return False
    # Izrecna privolitev uporabnika: naprava pride v ozji krog (obvestilo je to povedalo - telo_obvestila »ozji«).
    if not _dodaj_zmoznosti(j, odprte, ozji=True):
        _osvezi_prikaz(j)               # zapis ni uspel: prosnje ostanejo odprte, obvestilo se pokaze znova
        return False
    with _zaklep:
        # Z odobritvijo je naprava v ozjem krogu (ozji_krog): tudi prosnji za upravljanje in mape ne cakata vec.
        for c in set(odprte) | OZJI_KROG:
            _prosnje.pop(kljuc_prosnje(j, c), None)
            _zadnji_poziv.pop(kljuc_prosnje(j, c), None)
    print(f"[SafeerDostop] Uporabnik je dovolil: {j[:2]}…{j[-4:]} dobi {odprte}", flush=True)
    _osvezi_prikaz(j)
    return True


def zavrni_prosnjo(jedro_naprave: str, zmoznosti: str, zdaj: Optional[float] = None) -> bool:
    """Uporabnik je pritisnil Zavrni: nastetih prosenj (ena ali vec crk) 24 ur ne kazemo - velja tudi po ponovnem
    zagonu. Zavrne se vse nasteto, tudi ce kaksna prosnja vmes ni vec odprta."""
    par = razcleni_kljuc_skupine(kljuc_skupine(str(jedro_naprave or ""), str(zmoznosti or "")))
    if par is None:
        return False
    j, crke = par
    kljuci = [kljuc_prosnje(j, c) for c in crke]
    zdaj = time.time() if zdaj is None else zdaj

    def sprememba_ostalega(ostalo: dict) -> None:
        z = {k: t for k, t in _zavrnjeno_iz(ostalo.get("zavrnjeno")).items() if abs(zdaj - t) < ZAVRNITEV_VELJA_S}
        for k in kljuci:
            z[k] = zdaj
        ostalo["zavrnjeno"] = z
    with _zaklep:
        for k in kljuci:
            _prosnje.pop(k, None)
            _zavrnjeno[k] = zdaj         # v tem programu velja takoj, tudi ce zapis ne uspe
        _nalozen()
        try:
            _spremeni(lambda naprave, zascita: None, sprememba_ostalega)
        except OSError:
            pass
    print(f"[SafeerDostop] Uporabnik je zavrnil: {j[:2]}…{j[-4:]} ({crke}) za 24 ur", flush=True)
    _osvezi_prikaz(j)
    return True


#: Obvestilo s prosnjo je na zaslonu toliko sekund, nato se skrci v stevec na ikoni Safeer Link (pladenj Safeer
#: Controla), od koder ga uporabnik odpre znova. Prosnja ostane veljavna - nic se ne odobri ali zavrne samo
#: (lastnik, 17. 10. 2026: obvestilo je na testnem PC od polnoci stalo cez vsebino).
SKRCI_PO_S = 10.0


class ZdruzenPrikaz:
    """Prikaz prosenj z zamikom ZDRUZI_S na napravo: prosnje iste naprave, ki pridejo v tem casu, gredo v ENO
    obvestilo (prej so tri hkratne prosnje telefona pokazale tri obvestila). Ob prikazu se vsebina vzame sveza iz
    skupina_prosenj - kar je bilo vmes odobreno, zavrnjeno ali je izpadlo, se ne pokaze.

    `pokazi(skupina)` in `umakni(jedro)` sta prikaz programa (glavna nit); `razporedi(sekunde, klic)` klic odlozi
    (Control: GLib.timeout_add). `skrci(jedro)`: obvestilo, ki je bilo SKRCI_PO_S na zaslonu, gre z zaslona (prosnja
    ostane in jo kaze stevec). Velja za samostojni Safeer Control in za Control v procesu Safeer OS."""

    def __init__(self, pokazi: Callable[[dict], None], umakni: Callable[[str], None],
                 razporedi: Callable[[float, Callable[[], None]], object], cakaj_s: float = ZDRUZI_S,
                 skrci: Optional[Callable[[str], None]] = None, skrci_po_s: float = SKRCI_PO_S):
        self._pokazi, self._umakni, self._razporedi, self._cakaj_s = pokazi, umakni, razporedi, cakaj_s
        self._skrci, self._skrci_po_s = skrci, skrci_po_s
        self._cakajo: Set[str] = set()
        #: jedro -> zaporedna stevilka prikaza: skrci se samo zadnje obvestilo naprave (novo ima svoj rok).
        self._prikazi: Dict[str, int] = {}
        self._zaklep = threading.Lock()

    def pokazi(self, skupina: dict) -> None:
        j = str((skupina or {}).get("jedro") or "")
        if not _je_jedro(j):
            return
        with self._zaklep:
            if j in self._cakajo:
                return                  # ze caka na prikaz; takrat se vzame vse, kar je odprto
            self._cakajo.add(j)
        try:
            self._razporedi(self._cakaj_s, lambda: self._izvedi(j))
        except Exception:
            with self._zaklep:
                self._cakajo.discard(j)
            raise

    def umakni(self, kljuc: str) -> None:
        self._umakni(str(kljuc).partition("|")[0])

    def _izvedi(self, j: str) -> None:
        with self._zaklep:
            self._cakajo.discard(j)
        skupina = skupina_prosenj(j)
        try:
            if skupina is None:
                self._umakni(j)
            else:
                self._pokazi(skupina)
                self._skrci_pozneje(j)
        except Exception as e:  # noqa: BLE001 - obvestila ni bilo: napravi ob naslednjem poskusu povemo, da prosnje ni
            opusti_prosnje(j)
            print(f"[SafeerDostop] Prosnje ni bilo mogoce pokazati: {e}")

    def _skrci_pozneje(self, j: str) -> None:
        if self._skrci is None:
            return
        with self._zaklep:
            stevilka = self._prikazi.get(j, 0) + 1
            self._prikazi[j] = stevilka
        self._razporedi(self._skrci_po_s, lambda: self._skrci_ce(j, stevilka))

    def _skrci_ce(self, j: str, stevilka: int) -> None:
        with self._zaklep:
            if self._prikazi.get(j) != stevilka:
                return                  # medtem novo obvestilo iste naprave: skrci se ob svojem roku
            self._prikazi.pop(j, None)
        if skupina_prosenj(j) is not None and self._skrci is not None:
            self._skrci(j)

    def pokazi_znova(self) -> int:
        """Klik na stevec: obvestila vseh odprtih prosenj (eno na napravo) se pokazejo znova in se spet skrcijo.
        Vrne stevilo naprav."""
        jedra = list(dict.fromkeys(str(p.get("jedro") or "") for p in odprte_prosnje()))
        pokazane = 0
        for j in jedra:
            skupina = skupina_prosenj(j)
            if skupina is None:
                continue
            self._pokazi(skupina)
            self._skrci_pozneje(j)
            pokazane += 1
        return pokazane


def stevilo_cakajocih() -> int:
    """Stevec na ikoni Safeer Link: koliko naprav caka na odgovor (eno obvestilo na napravo)."""
    return len({str(p.get("jedro") or "") for p in odprte_prosnje()})


# ---------------------------------------------------------------------- obvestilo s prosnjo (Safeer Control)
#
# Namizno obvestilo »<naprava> prosi za dostop« z gumboma »Dovoli« in »Zavrni«. Klik na obvestilo samo odpre seznam
# naprav v Safeer Controlu - nikoli ne odobri. Gumba sta dejanji aplikacije Control s parametrom "<jedro>|<crka>";
# odobri se lahko samo prosnja, ki res caka (odobri_prosnjo). Gio, GLib in aplikacijo dobijo funkcije kot parametre
# (kot core/os_tema_namizja): ta modul ostane brez GTK, obvestilo pa je mogoce preizkusiti.

#: Imena dejanj aplikacije Safeer Control (samostojne in vgrajene v Safeer OS).
DEJANJE_DOVOLI = "dostop-dovoli"
DEJANJE_ZAVRNI = "dostop-zavrni"
DEJANJE_NAPRAVE = "dostop-naprave"
PREDPONA_ID = "safeer-dostop-"
NASLOV = "Safeer Link"

# »ozji«: naprava, ki z »Dovoli« pride v ozji krog, dobi tudi upravljanje in Safeer Vnos (ozji_krog) - obvestilo
# to pove, preden uporabnik pritisne (lastnik 25. 10. 2026 10:49: ena privolitev, jasno, kaj dovoli).
BESEDILA_OBVESTILA = {
    "sl": {"prosnja": "{ime} prosi za dostop: {kaj} na tem računalniku.", "dovoli": "Dovoli", "zavrni": "Zavrni",
           "d": "datoteke", "p": "programi", "v": "predvajalnik", "z": "zaslon, upravljanje in Safeer Vnos",
           "ozji": "Z »Dovoli« pride v ožji krog: dobi tudi upravljanje tega računalnika s Safeer Vnos (miška, tipkovnica) in tvoje mape (brez skritih map in ključev).",
           "dom": "Z »Dovoli« dobi tudi tvojo domačo mapo (brez skritih map in ključev)."},
    "en": {"prosnja": "{ime} is asking for access: {kaj} on this computer.", "dovoli": "Allow", "zavrni": "Deny",
           "d": "files", "p": "apps", "v": "player", "z": "screen, control and Safeer Input",
           "ozji": "Allow puts it in your inner circle: it also gets control of this computer with Safeer Input (mouse, keyboard) and your folders (without hidden folders and keys).",
           "dom": "Allow also gives it your home folder (without hidden folders and keys)."},
    "de": {"prosnja": "{ime} bittet um Zugriff: {kaj} auf diesem Computer.", "dovoli": "Erlauben", "zavrni": "Ablehnen",
           "d": "Dateien", "p": "Programme", "v": "Player", "z": "Bildschirm, Steuerung und Safeer Eingabe",
           "ozji": "Mit »Erlauben« kommt es in den engen Kreis: Es darf diesen Computer auch steuern, mit Safeer Eingabe (Maus, Tastatur), und sieht deine Ordner (ohne versteckte Ordner und Schlüssel).",
           "dom": "Mit »Erlauben« sieht es auch deinen persönlichen Ordner (ohne versteckte Ordner und Schlüssel)."},
    "es": {"prosnja": "{ime} pide acceso: {kaj} en este ordenador.", "dovoli": "Permitir", "zavrni": "Rechazar",
           "d": "archivos", "p": "programas", "v": "reproductor", "z": "pantalla, control y Safeer Entrada",
           "ozji": "Con «Permitir» entra en tu círculo de confianza: también podrá controlar este ordenador con Safeer Entrada (ratón, teclado) y ver tus carpetas (sin carpetas ocultas ni claves).",
           "dom": "Con «Permitir» también verá tu carpeta personal (sin carpetas ocultas ni claves)."},
    "fr": {"prosnja": "{ime} demande l'accès : {kaj} sur cet ordinateur.", "dovoli": "Autoriser", "zavrni": "Refuser",
           "d": "fichiers", "p": "programmes", "v": "lecteur", "z": "écran, contrôle et Safeer Saisie",
           "ozji": "« Autoriser » l'ajoute au cercle de confiance : il pourra aussi contrôler cet ordinateur avec Safeer Saisie (souris, clavier) et voir tes dossiers (sans dossiers cachés ni clés).",
           "dom": "« Autoriser » lui donne aussi ton dossier personnel (sans dossiers cachés ni clés)."},
    "it": {"prosnja": "{ime} chiede l'accesso: {kaj} su questo computer.", "dovoli": "Consenti", "zavrni": "Rifiuta",
           "d": "file", "p": "programmi", "v": "lettore", "z": "schermo, controllo e Safeer Input",
           "ozji": "Con «Consenti» entra nella cerchia ristretta: potrà anche controllare questo computer con Safeer Input (mouse, tastiera) e vedere le tue cartelle (senza cartelle nascoste né chiavi).",
           "dom": "Con «Consenti» vedrà anche la tua cartella home (senza cartelle nascoste né chiavi)."},
}

#: Stevec na ikoni Safeer Link: (ednina, mnozina) oz. v slovenscini (1, 2, 3-4, 5+).
BESEDILA_STEVCA = {
    "sl": ("{n} zahteva za dostop", "{n} zahtevi za dostop", "{n} zahteve za dostop", "{n} zahtev za dostop"),
    "en": ("{n} access request", "{n} access requests"),
    "de": ("{n} Zugriffsanfrage", "{n} Zugriffsanfragen"),
    "es": ("{n} solicitud de acceso", "{n} solicitudes de acceso"),
    "fr": ("{n} demande d'accès", "{n} demandes d'accès"),
    "it": ("{n} richiesta di accesso", "{n} richieste di accesso"),
}


def besedilo_stevca(jezik: Optional[str], n: int) -> str:
    oblike = BESEDILA_STEVCA.get((jezik or "en")[:2].lower(), BESEDILA_STEVCA["en"])
    n = int(n)
    if len(oblike) == 4:
        sto = n % 100
        oblika = oblike[0] if sto == 1 else oblike[1] if sto == 2 else oblike[2] if sto in (3, 4) else oblike[3]
    else:
        oblika = oblike[0] if n == 1 else oblike[1]
    return oblika.format(n=n)


def besedilo_obvestila(jezik: Optional[str], kljuc: str) -> str:
    return BESEDILA_OBVESTILA.get((jezik or "en")[:2].lower(), BESEDILA_OBVESTILA["en"]).get(
        kljuc, BESEDILA_OBVESTILA["en"].get(kljuc, kljuc))


def _crke(prosnja: dict) -> str:
    """Crke obvestila: "zmoznosti" (skupina) ali "zmoznost" (ena prosnja); samo znane, vsaka enkrat."""
    surovo = str(prosnja.get("zmoznosti") or prosnja.get("zmoznost") or "")
    izid = ""
    for c in surovo:
        if c in VSE_ZMOZNOSTI and c not in izid:
            izid += c
    return izid


def telo_obvestila(prosnja: dict, jezik: Optional[str]) -> str:
    """Besedilo obvestila: vse zaprosene zmoznosti z navadnimi besedami. Ime je iz kroga tega racunalnika in ze
    precisceno (cisto_ime)."""
    ime = cisto_ime(prosnja.get("ime")) or str(prosnja.get("jedro") or "")
    crke = _crke(prosnja)
    kaj = ", ".join(besedilo_obvestila(jezik, c) for c in crke)
    telo = besedilo_obvestila(jezik, "prosnja").format(ime=ime, kaj=kaj)
    # »Dovoli« napravo da v ozji krog (ozji_krog) z domaco mapo: ce v njem se ni in ne prosi za vse, kar ga sestavlja,
    # obvestilo pove, kaj se doda (upravljanje s Safeer Vnos, mape); ce domace mape se nima (tudi zapis d+z iz prejsnje
    # razlicice), pove vsaj to - privolitev mora biti informirana (vodja 25. 10. 2026).
    j = str(prosnja.get("jedro") or "")
    if crke and not _ima_dom_jedra(j):
        if not OZJI_KROG <= set(crke) and not OZJI_KROG <= zmoznosti_jedra(j):
            telo += " " + besedilo_obvestila(jezik, "ozji")
        else:
            telo += " " + besedilo_obvestila(jezik, "dom")
    return telo


def _ima_dom_jedra(j: str) -> bool:
    try:
        with _zaklep:
            naprave = _nalozen()
            return OZJI_KROG <= set(naprave.get(j) or ()) and j in _dom_disk
    except Exception:  # noqa: BLE001
        return False


def id_obvestila(kljuc: str) -> str:
    """Eno obvestilo na napravo: id je jedro (iz "<jedro>", "<jedro>|<crka>" ali "<jedro>|<crke>")."""
    return PREDPONA_ID + str(kljuc).partition("|")[0]


def razcleni_parameter(parameter) -> Optional[Tuple[str, str]]:
    """Parameter dejanja (GLib.Variant "s" ali niz) "<jedro>|<crke>" ali "<jedro>|<crke>|<zeton>" -> (jedro, crke) ali
    None. Zetona ne preveri (to naredi dejanje - glej registriraj_dejanja)."""
    par = _razcleni_parameter_z_zetonom(parameter)
    return (par[0], par[1]) if par is not None else None


def _razcleni_parameter_z_zetonom(parameter) -> Optional[Tuple[str, str, str]]:
    try:
        niz = parameter.get_string() if hasattr(parameter, "get_string") else parameter
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(niz, str):
        return None
    osnova, locilo, zeton = niz.rpartition("|") if niz.count("|") == 2 else (niz, "", "")
    par = razcleni_kljuc_skupine(osnova if locilo else niz)
    if par is None:
        return None
    return par[0], par[1], zeton


def _nov_zeton_gumbov(jedro_naprave: str) -> str:
    zeton = secrets.token_urlsafe(18)
    with _zaklep:
        _zetoni_gumbov[jedro_naprave] = zeton
    return zeton


def _porabi_zeton_gumbov(jedro_naprave: str, zeton: str) -> bool:
    """Zeton zadnjega obvestila naprave velja ENKRAT; star (obvestilo je bilo zamenjano) ali tuj ne velja."""
    with _zaklep:
        pravi = _zetoni_gumbov.get(jedro_naprave, "")
        if not pravi or not zeton or not hmac.compare_digest(pravi.encode("utf-8"), str(zeton).encode("utf-8")):
            return False
        _zetoni_gumbov.pop(jedro_naprave, None)
        return True


def poslji_obvestilo(app, Gio, GLib, prosnja: dict, jezik: Optional[str]) -> str:
    """Namizno obvestilo s prosnjami ene naprave; vrne njegov id (en na napravo - nova prosnja iste naprave zamenja
    starega). Gumba nosita natanko nastete crke: Dovoli odobri samo to, kar je uporabnik prebral - in enkraten zeton
    tega obvestila (dejanje brez njega ne naredi nicesar)."""
    kljuc = kljuc_skupine(str(prosnja.get("jedro") or ""), _crke(prosnja))
    parameter = kljuc + "|" + _nov_zeton_gumbov(str(prosnja.get("jedro") or ""))
    obvestilo = Gio.Notification.new(NASLOV)
    obvestilo.set_body(telo_obvestila(prosnja, jezik))
    try:
        from core import obvestila
        obvestilo.set_icon(Gio.ThemedIcon.new(obvestila.ikona(app)))
    except Exception:  # noqa: BLE001 - brez ikone je obvestilo enako uporabno
        pass
    # Navadna prioriteta: HIGH je v GLib »critical«, ki ga strežnik obvestil nikoli ne umakne sam (testni PC: obvestilo
    # je stalo od polnoci). Z zaslona gre po SKRCI_PO_S (ZdruzenPrikaz), prosnjo potem kaze stevec na ikoni Link.
    try:
        obvestilo.set_priority(Gio.NotificationPriority.NORMAL)
    except Exception:  # noqa: BLE001
        pass
    # Klik na obvestilo odpre seznam naprav (tam je tudi rocna nastavitev) - nikoli ne odobri.
    obvestilo.set_default_action("app." + DEJANJE_NAPRAVE)
    # Varna izbira prva (levo, prva za tipkovnico in daljinec - core/link_fokus); klik na obvestilo nikoli ne odobri.
    for gumb, dejanje in (("zavrni", DEJANJE_ZAVRNI), ("dovoli", DEJANJE_DOVOLI)):
        obvestilo.add_button_with_target(besedilo_obvestila(jezik, gumb), "app." + dejanje, GLib.Variant("s", parameter))
    ident = id_obvestila(kljuc)
    # Ena pot obvestil (core/obvestila.py): v procesu Safeer OS gre obvestilo pod Safeer OS kot vsa druga.
    from core import obvestila
    obvestila.poslji_gio(ident, obvestilo, app)
    return ident


def umakni_obvestilo(app, kljuc_prosnje: str) -> None:
    from core import obvestila
    obvestila.umakni(id_obvestila(kljuc_prosnje), app)


def registriraj_dejanja(app, Gio, GLib, dovoli: Callable[[str, str], object], zavrni: Callable[[str, str], object],
                        odpri_naprave: Callable[[], object]) -> None:
    """Dejanja »Dovoli«, »Zavrni« in »odpri seznam naprav« na aplikaciji Control. Dovoli/Zavrni sprejmeta samo
    parameter prave oblike "<jedro>|<crke>|<zeton>" z zetonom obvestila, ki ga je ta program pravkar pokazal
    (poslji_obvestilo) - enkrat; klic dobi (jedro, crke). Vse drugo se prezre."""
    def ob_odgovoru(klic):
        def obravnava(_dejanje, parameter) -> None:
            par = _razcleni_parameter_z_zetonom(parameter)
            if par is None:
                return
            if not _porabi_zeton_gumbov(par[0], par[2]):
                print("[SafeerControl] prosnja za dostop: dejanje brez veljavnega zetona obvestila prezrto", flush=True)
                return
            try:
                klic(par[0], par[1])
            except Exception as e:  # noqa: BLE001
                print("[SafeerControl] prosnja za dostop:", e, flush=True)
            umakni_obvestilo(app, par[0] + "|" + par[1])
        return obravnava
    # Na aplikaciji Control in na Safeer OS, ce tece v istem procesu: obvestilo gre prek Safeer OS (core/obvestila.py).
    from core import obvestila
    for cilj in obvestila.registriraj_na(app):
        for ime, klic in ((DEJANJE_DOVOLI, dovoli), (DEJANJE_ZAVRNI, zavrni)):
            dejanje = Gio.SimpleAction.new(ime, GLib.VariantType.new("s"))
            dejanje.connect("activate", ob_odgovoru(klic))
            cilj.add_action(dejanje)
        naprave = Gio.SimpleAction.new(DEJANJE_NAPRAVE, None)
        naprave.connect("activate", lambda _d, _p: odpri_naprave())
        cilj.add_action(naprave)


def _za_preizkus(pot: Optional[str]) -> None:
    """Preizkusi: zapis v zacasni datoteki (None vrne pravo pot)."""
    global _pot_preglasena, _zapis, _prebran_odtis, _prebrana_pot, _zascita, _zascita_disk, _zapis_spodletel_ob
    global _zavrnjeno_disk, _prikaz, _umik, _umik_casovnik, _migracija_caka_ob, _dom_disk
    with _zaklep:
        if _umik_casovnik is not None:
            _umik_casovnik.cancel()
        _umik_casovnik, _migracija_caka_ob = None, None
        _pot_preglasena, _zapis, _prebran_odtis, _prebrana_pot, _zascita = pot, None, None, "", set()
        _zascita_disk, _zapis_spodletel_ob = set(), None
        _zavrnjeno_disk, _prikaz, _umik = {}, None, None
        _dom_disk = set()
        _prosnje.clear()
        _zadnji_poziv.clear()
        _zavrnjeno.clear()
        _zetoni_gumbov.clear()
        _cakajo_umik.clear()
