"""Moji viri so enaki na vseh napravah v Safeer Linku - cista pravila za racunalnik (brez omrezja in diska).

Safeer OS za Android to zna od 3. 10. 2026 (SeznamiSink.kt, MedijskiViri.kt): vir, ki ga uporabnik doda na eni napravi
(dodatek, podkast, seznam, tok ...), se pojavi na vseh; izbris se prenese enako. Racunalnik (Linux, Windows) je bil do
kroga 85 izven tega - dodatek, dodan na telefonu, je bilo treba na racunalniku dodati se enkrat. Modul je skupen za
Linux in Windows; nic ne gre v oblak, samo med napravami v Linku.

Protokol (del odgovora na `lists.get {}`; glej core/seznami_sink.py):
  "sources":         [{"tip", "ime", "naslov", "cas"}]     cas = kdaj je bil vir dodan (ms; 0 = pred usklajevanjem)
  "sources_deleted": {"tip|naslov": cas}                    izbrisi, da se vir ne vrne z naprave, ki ga se ima

Vrste (kot na Androidu): stremio, peertube, splet, api, seznam, podkast, tok, tok-hls, tok-video, tok-hls-video.
Racunalnik doda se vrsto "url": naslov, ki ga je uporabnik dodal na racunalniku in mu vrsto doloci naprava sama (starejsa
razlicica Androida take vrste ne pozna in vnos preskoci).

Pravila:
  * zaseben dodatek (manifest `behaviorHints.adult`) ostane na napravi, kjer ga je uporabnik dodal - ne gre ven in ga
    ne prevzamemo; dokler ne vemo, ali je zaseben, velja kot zaseben;
  * racunalnik prevzame samo, kar zna predvajati (preveri ob prevzemu); cesar ne zna, si zapomni in ne poskusa znova
    ob vsakem usklajevanju; spletnih strani, streznikov PeerTube in virov API ne prevzema;
  * isti vir: dodatek po korenu (brez /manifest.json), drugo po naslovu - ne glede na vrsto, ki mu jo je dala naprava;
  * dodatek z osebnim zetonom ali kljucem v naslovu ne gre ven in ga ne prevzamemo (javen_naslov, 25. 10. 2026).
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.parse
from typing import Optional

from core import skrivni_dodatki

#: Vrsta vira, ki ga je uporabnik dodal na racunalniku (vrsto doloci naprava, ki ga prevzame).
URL = "url"
STREMIO = "stremio"
_VRSTE = re.compile(r"^(stremio|peertube|splet|api|seznam|podkast|tok(-hls)?(-video)?|url)$")
#: Kar racunalnik zna prevzeti: dodatke in naslove, ki jih prebere Medijski center. Strezniki PeerTube in viri API imajo
#: na Androidu svoj zapis, ki ga racunalnik ne pozna. Spletna stran ("splet": youtube.com, open.spotify.com) je na
#: Androidu bliznjica do strani v brskalniku; Medijski center na racunalniku bi iz nje pobral nakljucne vnose s prve
#: strani (preizkus v zivo, 3. 10. 2026), zato je ne prevzamemo - za strani ima racunalnik Spletne aplikacije.
PREVZEMLJIVE = frozenset({STREMIO, "seznam", "podkast", "tok", "tok-hls", "tok-video", "tok-hls-video", URL})
NAJVEC_VIROV = 200
NAJVEC_IZBRISANIH = 300
#: Vir, ki ga racunalnik ni mogel prevzeti (ni predvajljiv, zaseben, nedosegljiv), poskusimo znova sele cez toliko.
ZAVRNJEN_VELJA_MS = 24 * 3600 * 1000
NEDOSEGLJIV_VELJA_MS = 10 * 60 * 1000


def stremio_osnova(naslov: str) -> str:
    """Koren dodatka: brez stremio://, /manifest.json in koncne posevnice (kot Stremio.osnova na Androidu)."""
    n = str(naslov or "").strip()
    if n.startswith("stremio://"):
        n = "https://" + n[len("stremio://"):]
    if n.endswith("/manifest.json"):
        n = n[:-len("/manifest.json")]
    return n.rstrip("/")


def stremio_naslov(naslov: str) -> str:
    """Naslov dodatka, kot ga hrani Android: naslov manifesta."""
    return stremio_osnova(naslov) + "/manifest.json"


def kljuc(tip: str, naslov: str) -> str:
    return str(tip or "") + "|" + str(naslov or "")


def istovetnost(tip: str, naslov: str) -> str:
    """Po cem je vir isti na vseh napravah: dodatek po korenu, drugo po naslovu (vrsta je lahko na napravah razlicna)."""
    if tip == STREMIO:
        return "s:" + stremio_osnova(naslov).lower()
    return "u:" + str(naslov or "").strip().rstrip("/")


def istovetnost_kljuca(k: str) -> str:
    tip, _, naslov = str(k or "").partition("|")
    return istovetnost(tip, naslov)


def cist_vir(o: object) -> Optional[dict]:
    """Vir z druge naprave: znana vrsta, javen naslov, razumna dolzina - nic drugega ne prevzamemo."""
    if not isinstance(o, dict):
        return None
    tip, ime, naslov = str(o.get("tip") or ""), str(o.get("ime") or ""), str(o.get("naslov") or "")
    cas = o.get("cas")
    if not _VRSTE.fullmatch(tip) or not 4 <= len(naslov) <= 2048 or len(ime) > 200:
        return None
    if any(c < " " for c in naslov) or any(c < " " for c in ime):
        return None
    if tip != "peertube" and not naslov.startswith(("http://", "https://")):
        return None
    if not javen_naslov(tip, naslov):
        return None
    return {"tip": tip, "ime": ime, "naslov": naslov,
            "cas": int(cas) if isinstance(cas, (int, float)) and not isinstance(cas, bool) and cas > 0 else 0}


def javen_naslov(tip: str, naslov: str) -> bool:
    """Vir sme med vse naprave v Linku: dodatek z osebnim zetonom ali kljucem (Webtor, Torrentio z debrid kljucem) in
    katerikoli nadomestek ne (core/skrivni_dodatki.py) - ne gre ven in ga ne prevzamemo. Pred 25. 10. 2026 je tak
    dodatek z lists.get sel vsem napravam (zeton v cistopisu). Ozjega kroga za kljuce namizje se nima."""
    naslov = str(naslov or "")
    if skrivni_dodatki.je_nadomestek(naslov):
        return False
    return tip != STREMIO or skrivni_dodatki.sme_med_vse_naprave(naslov)


def javen_kljuc(k: str) -> bool:
    """Kljuc izbrisa "tip|naslov" brez skrivnosti dodatka in brez nadomestka."""
    tip, _, naslov = str(k or "").partition("|")
    return javen_naslov(tip, naslov)


def vir_prevzamemo(imam: bool, moj_izbris: Optional[int], tuj_cas: int) -> bool:
    """Vir z druge naprave prevzamemo, ce ga tu ni in ga tu nismo izbrisali pozneje (ali hkrati), kot je bil tam dodan
    (SeznamiPravila.virPrevzamemo)."""
    return not imam and (-1 if moj_izbris is None else int(moj_izbris)) < int(tuj_cas or 0)


def izbris_vira_velja(moj_cas: int, tuj_izbris: int) -> bool:
    """Izbris vira na drugi napravi velja tudi tukaj, ce vira tu nismo dodali pozneje (SeznamiPravila.izbrisViraVelja)."""
    return int(tuj_izbris or 0) > 0 and int(tuj_izbris) > int(moj_cas or 0)


def nov_cas(zdaj: int, prej: int = 0, izbrisan: int = 0) -> int:
    """Cas krajevne spremembe: nikoli starejsi od prejsnjega stanja in znanega izbrisa (ure naprav niso enake)."""
    return max(int(zdaj), int(prej or 0) + 1, int(izbrisan or 0) + 1)


def cas_izbrisa(izbrisani: dict, tip: str, naslov: str) -> Optional[int]:
    """Kdaj smo ta vir tukaj izbrisali (ne glede na vrsto v kljucu); None = nikoli."""
    i = istovetnost(tip, naslov)
    casi = [int(c) for k, c in (izbrisani or {}).items() if isinstance(c, (int, float)) and istovetnost_kljuca(k) == i]
    return max(casi) if casi else None


def cisti_izbrisi(d: object) -> dict:
    """`sources_deleted` z druge naprave: {"tip|naslov": cas} z znano vrsto in pozitivnim casom."""
    if not isinstance(d, dict):
        return {}
    izid = {}
    for k, c in list(d.items())[:NAJVEC_IZBRISANIH]:
        if not isinstance(k, str) or len(k) > 2100 or not isinstance(c, (int, float)) or isinstance(c, bool) or c <= 0:
            continue
        if _VRSTE.fullmatch(k.partition("|")[0]) and javen_kljuc(k):
            izid[k] = int(c)
    return izid


def obrezi_izbrisane(izbrisani: dict) -> dict:
    """Najvec [NAJVEC_IZBRISANIH] zadnjih izbrisov."""
    return dict(sorted(izbrisani.items(), key=lambda kv: kv[1], reverse=True)[:NAJVEC_IZBRISANIH])


# ------------------------------------------------------------------ prijava osebnih streznikov v naslovih
# Skladbe osebnih streznikov imajo prijavo v naslovu toka in ovitka: Jellyfin `ApiKey=<zeton>` (prej `api_key`), Emby
# `api_key`, Navidrome/Subsonic `u=…&t=md5(geslo+sol)&s=…`, Plex `X-Plex-Token`, Funkwhale `token`, Kodi in TVHeadend
# `uporabnik:geslo@`. Taki naslovi ne smejo v sezname, police ali na druge naprave (pregled 14. 10. 2026: »Shrani kot
# seznam« jih je pisal v seznami.json, lists.get pa jih je dal napravam v Linku). Shranimo naslov brez prijave;
# Medijski center jo doda ob predvajanju iz zbirke skrivnosti (MediaCenter.s_prijavo).

#: Parametri, ki so prijava ne glede na pot (male crke).
PARAMETRI_PRIJAVE = frozenset({"api_key", "apikey", "x-emby-token", "x-mediabrowser-token", "token", "access_token",
                               "x-plex-token"})
#: Parametri Subsonic API (Navidrome, Airsonic …): kratka imena, zato samo na poti /rest/ ali *.view - drugje (npr.
#: `t=` cas v posnetku) jih ne odstranimo.
PARAMETRI_SUBSONIC = frozenset({"u", "t", "s", "p"})


def je_subsonic(pot: str) -> bool:
    pot = str(pot or "").lower()
    return "/rest/" in pot or pot.startswith("rest/") or pot.endswith(".view")


def brez_prijave(url: object) -> str:
    """Naslov brez prijave: brez uporabnika in gesla pred gostiteljem in brez parametrov prijave. Drugo ostane enako."""
    besedilo = str(url or "")
    if not besedilo.lower().startswith(("http://", "https://")):
        return besedilo
    try:
        d = urllib.parse.urlsplit(besedilo)
    except ValueError:
        return ""
    gostitelj = d.netloc.rpartition("@")[2]
    subsonic = je_subsonic(d.path)
    deli = [x for x in d.query.split("&") if x]
    ostali = [x for x in deli if not (urllib.parse.unquote_plus(x.partition("=")[0]).lower() in PARAMETRI_PRIJAVE
                                     or (subsonic and urllib.parse.unquote_plus(x.partition("=")[0]).lower() in PARAMETRI_SUBSONIC))]
    if gostitelj == d.netloc and len(ostali) == len(deli):
        return besedilo
    return urllib.parse.urlunsplit((d.scheme, gostitelj, d.path, "&".join(ostali), d.fragment))


def ima_prijavo(url: object) -> bool:
    """Ali ima naslov prijavo (zeton, geslo ali uporabnika pred gostiteljem)."""
    return brez_prijave(url) != str(url or "")


#: Javni dodatek Stremio brez kljuca (Android StremioPravila JAVNI_DODATKI); enako media_servers.CINEMETA.
CINEMETA_MANIFEST = "https://v3-cinemeta.strem.io/manifest.json"


def znan_javen(naslov: object, oznacen: bool = False) -> bool:
    """Ali je vir POZITIVNO znan kot javen, brez racuna (pregled 46, Ö1 - ob dvomu ne, kot preverba v ozadju v
    pregledu 39, I1): naslov http(s) brez presledkov in nevidnih znakov, brez prijave ali racuna v naslovu (ima_prijavo,
    kanali_iptv.s_poverilnicami) IN znan javni seznam (kanali_iptv.ZNANI_JAVNI_VIRI, Android IptvPravila.JAVNI_SEZNAMI)
    ali ga je uporabnik izrecno oznacil kot javnega (`oznacen`: vir["javni"] is True). Samo tak gre napravam zunaj
    ozjega kroga in na zaslon s celim naslovom. Vse drugo velja za vir z racunom: tudi oblike, ki jih nobena hevristika
    ne pozna (.../playlist/<u>/<g>/m3u_plus, zeton v poti, kratka povezava, rtsp://, zasebni podkast, dodatek s kljucem
    debrid v poti)."""
    besedilo = naslov if isinstance(naslov, str) else ""
    if not besedilo or len(besedilo) > 2048 or not besedilo.isprintable() or " " in besedilo:
        return False
    if not besedilo.lower().startswith(("http://", "https://")):
        return False
    from . import kanali_iptv
    if ima_prijavo(besedilo) or kanali_iptv.s_poverilnicami(besedilo, seznam=True):
        return False
    # Javni dodatek Stremio brez kljuca: samo tocen naslov Cinemete (enako kot Android StremioPravila JAVNI_DODATKI, Ñ1);
    # po zdruzitvi kljuci-namizje + mc-iptv-serije (26. 10. 2026) ga je sicer izvoz izpustil (test_skrivni_dodatki).
    # Brez uvoza media_servers: ta ni v tovoru Safeer Control (Grok 82, Ĥ1) - naslov je zapisan tu, enak media_servers.CINEMETA.
    return kanali_iptv.znan_javni_vir(besedilo) or besedilo == CINEMETA_MANIFEST or oznacen is True


def za_ozji_krog(naslov: object, oznacen: bool = False) -> bool:
    """Vir gre drugim napravam samo v ozji krog (core/link_dostop.v_ozjem_krogu), razen ce je pozitivno znan javen
    (znan_javen). Z Androida, VISOKO, 26. 10. 2026: seznam Xtream z geslom je sel z usklajevanjem virov na vse naprave
    v Linku z dovoljenjem »Predvajalnik«; pregled 46, Ö1: hevristika je ob neznani obliki odprla."""
    return not znan_javen(naslov, oznacen)


def prikaz_naslova(naslov: object, oznacen: bool = False) -> str:
    """Naslov za zaslon: cel samo pozitivno znan javen vir (znan_javen), vse drugo samo gostitelj[:vrata] - geslo ali
    zeton ni nikjer na zaslonu (enako Android). Brez gostitelja: prazno."""
    besedilo = str(naslov or "")
    if znan_javen(besedilo, oznacen):
        return besedilo
    try:
        d = urllib.parse.urlsplit(besedilo.strip())
        gostitelj, vrata = d.hostname or "", d.port
    except ValueError:
        return ""
    if not gostitelj or not gostitelj.isprintable() or " " in gostitelj:
        return ""
    if ":" in gostitelj:
        gostitelj = "[%s]" % gostitelj
    return gostitelj + (":%d" % vrata if vrata else "")


def zaznan_racun(naslov: object) -> bool:
    """Racun, ki ga hevristika prepozna (prijava, Xtream, username=, mac=, zeton seznama). Samo za vire naprave
    starejse razlicice (prevzem_dovoljen) in opozorilo lastniku; kam gre vir, odloca znan_javen."""
    besedilo = str(naslov or "")
    from . import kanali_iptv
    return ima_prijavo(besedilo) or kanali_iptv.s_poverilnicami(besedilo, seznam=True)


def prevzem_dovoljen(naslov: object, ozji_odgovor: object) -> bool:
    """Ali vir z druge naprave prevzamemo (pregled 46, Ö3). Odgovor `lists.get` od te razlicice naprej pove, ali nas
    ima naprava v ozjem krogu ("ozji"): true - vsak vir; false - samo pozitivno znan javen (drugega nam ne bi smela
    poslati). Naprava starejse razlicice ("ozji" ga ni) je dala vse vire vsem in ne vemo, ali nas ima v ozjem krogu:
    ob dvomu ne (pregled 51, Ê3) - prevzamemo samo pozitivno znan javen vir, kot pri odgovoru false. Heuristika
    zaznan_racun bi shranila vir z geslom neprepoznane oblike (…/playlist/<u>/<g>/m3u_plus, zeton v poti) na napravo, ki
    morda ni v ozjem krogu. Vir z racunom pride, ko se posodobi se posiljatelj."""
    if ozji_odgovor is True:
        return True
    return znan_javen(naslov)


#: Stanje prejetega vira (skupni primeri iptv-racun.json, razdelek ozji_krog, verzija 5 - enako Android).
STANJE_JAVEN = "javen"                  # pozitivno znan javen vir: prenos takoj
STANJE_PRVA_UPORABA = "prvo_uporaba"    # vir z racunom ali neznane oblike iz ozjega kroga: viden takoj, prva povezava ob uporabi
STANJE_NI_PREVZET = "ni_prevzet"        # brez dokaza o ozjem krogu vira z racunom ne prevzamemo (prevzem_dovoljen)


def stanje_prejetega(naslov: object, ozji_odgovor: object, posiljatelj_v_krogu: bool = False) -> str:
    """Kaj naredimo z virom z druge naprave (lastnik, 26. 10. 2026: vse naprave pripadajo uporabniku). Naprava, ki nas ima
    v ozjem krogu (`ozji` true), vir z racunom ali neznane oblike pokaze takoj, a ga ne osvezuje v ozadju: prva
    povezava je ob prvi uporabi na tej napravi. Odgovor false ali brez zastavice (starejsa razlicica, neznan izvor) ostane
    fail-closed: vira z racunom sploh ne prevzamemo. Vir, ki ga kdo vseeno doda brez dokaza o ozjem krogu (add_source brez
    ozji_krog), caka uporabnikovo osvezitev (skupni primeri, razdelek caka).

    Pregled 68, Ą3 (verzija 6 skupnih primerov): odgovor »ozji« je samo izjava posiljatelja, da ima NAS v svojem krogu.
    Dokaz je sele to, da je posiljatelj v ozjem krogu TE naprave (`posiljatelj_v_krogu`, core/link_dostop); brez
    obojega vira z racunom ne prevzamemo (nobeno sporocilo druge naprave ne podeli dostopa)."""
    if znan_javen(naslov):
        return STANJE_JAVEN
    return STANJE_PRVA_UPORABA if (ozji_odgovor is True and posiljatelj_v_krogu is True) else STANJE_NI_PREVZET


def verjetno_geslo(naslov: object, seznam_iptv: bool = False, oznacen: bool = False) -> bool:
    """Za opozorilo lastniku (pregled 46, Ö3): vir, ki ni znan javen, ima v naslovu prepoznan racun ali je seznam
    kanalov IPTV (ponudnik ima racun tudi v oblikah naslova, ki jih hevristika ne pozna). Podkast brez racuna: ne."""
    return za_ozji_krog(naslov, oznacen) and (zaznan_racun(naslov) or seznam_iptv is True)


#: Oblika naslova seznama IPTV z racunom, ki ga zaznan_racun ne prepozna: …/playlist/<u>/<g>/…, …/get/<u>/<g>/…, m3u_plus.
_OBLIKA_SEZNAMA = re.compile(r"/playlist/[^/?#]+/[^/?#]+/|/get/[^/?#]+/[^/?#]+/|m3u8?_plus|/get\.php|/player_api\.php|"
                             r"/xmltv\.php", re.IGNORECASE)
#: Pri izbrisanem viru (opozorilo, ob dvomu da) zadostuje vsaka sled seznama.
_SLED_SEZNAMA = re.compile(r"m3u|/playlist|iptv", re.IGNORECASE)


def verjetno_racun_seznama(naslov: object, oznacen: bool = False, siroko: bool = False) -> bool:
    """Naslov, ki ni znan javen in ima prepoznan racun ali obliko seznama IPTV z racunom (pregled 51, Ê1: premor in
    odsotnost rezervne zahteve; Ê2: izbrisan vir ima samo se naslov, zato seznama kanalov ne moremo pogledati - tam
    `siroko`, ker je opozorilo neskodljivo). Podkast ali stran brez racuna ter navaden seznam .m3u: ne."""
    besedilo = str(naslov or "")
    return za_ozji_krog(besedilo, oznacen) and (zaznan_racun(besedilo) or bool(_OBLIKA_SEZNAMA.search(besedilo))
                                               or (siroko and bool(_SLED_SEZNAMA.search(besedilo))))


def _oznacen(v: object) -> bool:
    """Uporabnik je vir izrecno oznacil kot javnega (samo seznam IPTV brez racuna, MediaCenter.nastavi_javni_seznam)."""
    return isinstance(v, dict) and v.get("javni") is True


#: Ponudnik Usenet za ozji krog (naloga 114, core/usenet_vezava.za_krog): samo ta polja, nikoli gesla. Kljuc v
#: odgovoru `lists.get` je USENET_PONUDNIK; zunaj ozjega kroga ga ni.
USENET_PONUDNIK = "usenet_ponudnik"
_USENET_POLJA = {"gostitelj": str, "uporabnik": str, "vrata": int, "tls": bool, "najvec_povezav": int, "ime": str}
_USENET_DOLZINE = {"gostitelj": 253, "uporabnik": 400, "ime": 80}


#: Imena, ki ne vodijo v internet (domace omrezje, ta racunalnik) - ponudnik iz ozjega kroga tja ne sme kazati.
_USENET_DOMACA_IMENA = (".local", ".localhost", ".localdomain", ".lan", ".home", ".home.arpa", ".internal", ".intranet")


def javni_gostitelj_usenet(gostitelj: str) -> bool:
    """Neodvisen pregled 118 S1 (27. 10. 2026): ponudnik, ki ga poslje druga naprava, sme kazati samo na javni internet.
    Sicer bi vdrta naprava v krogu dolocila naslov v domacem omrezju in Safeer bi tja (po uporabnikovem vpisu gesla)
    odprl TLS in poslal prijavo. Naslov IP mora biti javen (ne domace, povratno, link-local ali rezervirano omrezje);
    ime mora imeti piko in ne sme biti eno od domacih imen. Ime, ki se razresi v domace omrezje, ujame se jedro ob povezavi."""
    g = (gostitelj or "").strip().lower().rstrip(".")
    if not g:
        return False
    try:
        return ipaddress.ip_address(g.strip("[]")).is_global
    except ValueError:
        pass
    if "." not in g or g == "localhost" or any(g.endswith(k) for k in _USENET_DOMACA_IMENA):
        return False
    return True


def cist_usenet(o: object) -> Optional[dict]:
    """Zapis ponudnika Usenet z druge naprave ali za njo: tocno znana polja prave vrste, samo TLS. Polje, ki ga ne
    poznamo (tudi »geslo«), zapis zavrne v celoti - ne samo odrezemo: tuj ali spremenjen zapis ne pride naprej.
    Brez uvoza core/usenet_ponudnik: modul uporablja tudi Safeer Control (core/link_seznami.py)."""
    if not isinstance(o, dict) or set(o) != set(_USENET_POLJA):
        return None
    for k, vrsta in _USENET_POLJA.items():
        v = o[k]
        if not isinstance(v, vrsta) or (vrsta is int and isinstance(v, bool)):
            return None
        if isinstance(v, str) and (len(v) > _USENET_DOLZINE[k] or any(c < " " or c == "\x7f" for c in v)):
            return None
    if o["tls"] is not True or not o["gostitelj"] or not o["uporabnik"] or not javni_gostitelj_usenet(o["gostitelj"]):
        return None
    if not 1 <= o["vrata"] <= 65535 or not 1 <= o["najvec_povezav"] <= 100:
        return None
    return {k: o[k] for k in _USENET_POLJA}


def razdeli_izvoz(viri: list, izbrisani: dict, usenet: object = None) -> dict:
    """Zapis virov za naprave (viri_za_naprave.json): zgoraj samo pozitivno znani javni viri in njihovi izbrisi (oznaka
    »javni« ostane v zapisu za viri_za), vse drugo pod »ozji«. Ponudnik Usenet ([usenet], brez gesla) je samo pod
    »ozji« (naloga 114)."""
    javni = [v for v in viri if znan_javen(v.get("naslov"), _oznacen(v))]
    javni_izbrisi = {k: c for k, c in izbrisani.items() if znan_javen(str(k).partition("|")[2])}
    ozji = {"sources": [v for v in viri if not znan_javen(v.get("naslov"), _oznacen(v))][:NAJVEC_VIROV],
            "sources_deleted": {k: c for k, c in izbrisani.items() if k not in javni_izbrisi}}
    u = cist_usenet(usenet)
    if u is not None:
        ozji[USENET_PONUDNIK] = u
    return {"sources": javni[:NAJVEC_VIROV], "sources_deleted": javni_izbrisi, "ozji": ozji}


def viri_za(izvoz: object, ozji: bool = False) -> dict:
    """Viri za odgovor `lists.get` iz razdeli_izvoz: napravi v ozjem krogu vsi, drugim samo pozitivno znani javni -
    tudi ce je kaj drugega v javnem delu (zapis starejse razlicice ali hevristike pred pregledom 46)."""
    izvoz = izvoz if isinstance(izvoz, dict) else {}

    def cisti(surovi: object) -> list:
        surovi = surovi if isinstance(surovi, list) else []
        return [(c, _oznacen(o)) for c, o in ((cist_vir(o), o) for o in surovi[:NAJVEC_VIROV]) if c]
    viri = cisti(izvoz.get("sources"))
    izbrisi = cisti_izbrisi(izvoz.get("sources_deleted"))
    usenet = None
    if ozji:
        o = izvoz.get("ozji") if isinstance(izvoz.get("ozji"), dict) else {}
        viri += cisti(o.get("sources"))
        izbrisi.update(cisti_izbrisi(o.get("sources_deleted")))
        # Samo iz dela »ozji«: ponudnik v javnem delu (zapis, ki ga je kdo spremenil) ne gre nikomur.
        usenet = cist_usenet(o.get(USENET_PONUDNIK))
    else:
        viri = [(c, z) for c, z in viri if znan_javen(c["naslov"], z)]
        izbrisi = {k: c for k, c in izbrisi.items() if znan_javen(k.partition("|")[2])}
    izid = {"sources": [c for c, _z in viri][:NAJVEC_VIROV], "sources_deleted": izbrisi}
    if usenet is not None:
        izid[USENET_PONUDNIK] = usenet
    return izid


#: Gostitelji slik, ki so pozitivno javni (ovitki YouTube in Spotify iz uvoza seznamov, core/uvoz_seznama.py): taka
#: slika skladbe gre tudi napravi zunaj ozjega kroga. Druge (logotip ponudnika IPTV, ovitek osebnega streznika) samo
#: ozjemu krogu (pregled 46, Ö2).
JAVNE_SLIKE = frozenset({"i.ytimg.com", "img.youtube.com", "i.scdn.co", "mosaic.scdn.co", "image-cdn-ak.spotifycdn.com",
                         "image-cdn-fa.spotifycdn.com"})
_NASLOV_V_BESEDILU = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>\\]+")
#: Ime polja ali parametra z racunom v zapisu Androida (JSON ali poizvedba): username, password, token, mac ...
_RACUN_V_BESEDILU = re.compile(r"(?i)\b(user(name)?|pass(word|wd)?|pwd|login|token|access_token|private_token|api_?key|"
                               r"auth|mac)[\"']?\s*[:=]")


def javna_slika(naslov: object) -> bool:
    """Slika z znanega javnega gostitelja (JAVNE_SLIKE), https, brez prijave ali racuna v naslovu - ali znan javen vir."""
    besedilo = naslov if isinstance(naslov, str) else ""
    if not besedilo.startswith("https://") or not besedilo.isprintable() or " " in besedilo:
        return False
    from . import kanali_iptv
    if ima_prijavo(besedilo) or kanali_iptv.s_poverilnicami(besedilo, seznam=True):
        return False
    try:
        gostitelj = (urllib.parse.urlsplit(besedilo).hostname or "").lower()
    except ValueError:
        return False
    return gostitelj in JAVNE_SLIKE or znan_javen(besedilo)


def zapis_androida_javen(zapis: object) -> bool:
    """Zapis naprave Android (`android`, ki ga racunalnik le prenese naprej) sme napravi zunaj ozjega kroga samo, ce v
    njem ni racuna (username=, "password": ...) in so vsi naslovi v njem pozitivno javni. Zapis JSON se pred tem
    razcleni in zapise znova brez ubeznic (\\/ in \\u003d ne skrijeta naslova ali gesla)."""
    besedilo = zapis if isinstance(zapis, str) else ""
    try:
        besedilo = json.dumps(json.loads(besedilo), ensure_ascii=False)
    except ValueError:
        besedilo = besedilo.replace("\\/", "/")
    except RecursionError:
        return False                    # pregloboko gnezden zapis: ne vemo, kaj je notri - ob dvomu ne
    if _RACUN_V_BESEDILU.search(besedilo):
        return False
    # Pregled 95, Ĵ2 (26. 10. 2026): kljuc z imenom storitve ali koncnico (torboxKey, realdebrid, secret ...) vzorec
    # racuna ne prepozna - ista prepoznava kot za nastavitve dodatkov (skrivni_dodatki.ima_kljucno_polje).
    if skrivni_dodatki.ima_kljucno_polje(besedilo):
        return False
    naslovi = _NASLOV_V_BESEDILU.findall(besedilo)
    if besedilo.count("//") != len(naslovi):
        return False                    # naslov brez sheme (//gostitelj/...) ali nerazumljiv zapis
    return all(znan_javen(n) or javna_slika(n) for n in naslovi)


#: Naslov s shemo v besedilu napake: do presledka, BREZ ustavljanja pri navednici, <, > ali \\ (pregled 57, Ş5: geslo z '
#: ali " je prekinilo ujemanje in ostanek naslova z geslom je ostal na zaslonu).
_NASLOV_V_NAPAKI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*")
#: Zacetek cilja zahteve ali racuna v besedilu napake, neodvisno od zapisa izjeme (repr, %s, navednice):
#: navednica pred potjo ali poizvedbo ('/get.php?…', "/playlist/…"; http.client.InvalidURL nosi cilj brez sheme),
#: pot z vsaj dvema odsekoma brez navednic, parameter poizvedbe (?a=, &a=) in imena polj z racunom (username=, password= ...).
_ZACETEK_CILJA = re.compile(
    r"""(?P<navednica>['"])(?=[/?])"""
    r"""|(?<![\w.~%:-])/[\w.~%-]+/[\w~%-]"""
    r"""|[?&;][\w.%~-]+="""
    r"""|\b(?:user(?:name)?|pass(?:word|wd)?|pwd|token|access_token|api_?key|mac|auth|login)=""", re.IGNORECASE)
#: Odseki poti in vrednosti parametrov, ki niso skrivnost (obstojijo v vsakem naslovu seznama, zakrivanje jih ne sme trgati).
_SPLOSNI_ODSEKI = frozenset({"live", "movie", "movies", "series", "get", "get.php", "playlist", "player_api.php", "xmltv.php",
                             "panel_api.php", "stream", "streams", "m3u", "m3u8", "m3u_plus", "m3u8_plus", "mpegts", "hls",
                             "json", "xml", "true", "false"})


def skrivnosti_naslova(naslov: object) -> list:
    """Deli naslova, ki so lahko geslo ali zeton: uporabnik in geslo pred gostiteljem, vrednosti parametrov poizvedbe (v
    surovi in odkodirani obliki) in odseki poti (tudi brez koncnice), brez splosnih (_SPLOSNI_ODSEKI) in krajsih od 3
    znakov. Za zakrivanje po TOCNEM ujemanju v besedilu napake: ne zavisi od zapisa izjeme (navednice, repr) ali od
    dolzine sporocila (pregled 57, Ş5). Najdaljse najprej."""
    besedilo = str(naslov or "").strip()
    del_za_shemo = besedilo.partition("://")[2] if "://" in besedilo else besedilo
    pred_potjo, _, pot_in_naprej = del_za_shemo.partition("/")
    pot, _, ostanek = pot_in_naprej.partition("?")
    poizvedba = ostanek.partition("#")[0]
    kandidati: list = []
    if "@" in pred_potjo:
        prijava = pred_potjo.rpartition("@")[0]
        kandidati += [prijava] + prijava.split(":")
    for del_ in poizvedba.replace(";", "&").split("&"):
        kandidati.append(del_.partition("=")[2])
    for odsek in pot.split("/"):
        kandidati += [odsek, odsek.rpartition(".")[0]]
    izid: dict = {}
    for k in kandidati:
        for oblika in (k, urllib.parse.unquote_plus(k)):
            if len(oblika) >= 3 and oblika.lower() not in _SPLOSNI_ODSEKI:
                izid[oblika] = True
    return sorted(izid, key=len, reverse=True)


def _zadnja_neubezna(besedilo: str, navednica: str, od: int) -> int:
    """Mesto zadnje navednice (od `od` naprej), pred katero ni lihega stevila posevnic nazaj: repr zapise ' v nizu kot
    \\' in taka navednica NI zakljucna. -1: ni je (besedilo je odrezano ali niz ni zakljucen - skrijemo do konca)."""
    i = besedilo.rfind(navednica, od)
    while i >= od:
        n = 0
        while i - n - 1 >= 0 and besedilo[i - n - 1] == "\\":
            n += 1
        if n % 2 == 0:
            return i
        i = besedilo.rfind(navednica, od, i)
    return -1


def _zakrij_cilje(besedilo: str) -> str:
    """Besedilo napake brez cilja zahteve in racuna: vse od zacetka cilja (_ZACETEK_CILJA) naprej do ZAKLJUCNE navednice
    iste vrste (ali do konca besedila) postane »…«; pot brez navednic do presledka. Ni odvisno od tega, kako je izjema
    zapisala naslov: geslo z ' ali " (repr ga zapise v "…" ali z \\'), presledek v cilju ali dolgo besedilo ne pustijo
    ostanka (pregled 57, Ş5; pregled 51, Ê5). Ob dvomu raje skrije vec."""
    izid, poz = [], 0
    while True:
        m = _ZACETEK_CILJA.search(besedilo, poz)
        if m is None:
            break
        navednica = m.group("navednica")
        if navednica:
            odprta = m.start()
        else:
            odprta = m.start()
            while odprta > poz and not besedilo[odprta - 1].isspace() and besedilo[odprta - 1] not in "'\"":
                odprta -= 1
            if odprta > poz and besedilo[odprta - 1] in "'\"":          # cilj je v navednicah, ki se zacnejo pred njim
                navednica = besedilo[odprta - 1]
                odprta -= 1
        izid.append(besedilo[poz:odprta])
        if navednica:
            konec = _zadnja_neubezna(besedilo, navednica, odprta + 1)
            if konec < 0:
                izid.append(navednica + "…")
                poz = len(besedilo)
            else:
                izid.append(navednica + "…" + navednica)
                poz = konec + 1
        else:
            konec = m.end()
            while konec < len(besedilo) and not besedilo[konec].isspace():
                konec += 1
            izid.append("…")
            poz = konec
    izid.append(besedilo[poz:])
    return "".join(izid)


def zakrij_naslove(besedilo: object, napaka: bool = False, tajno: object = ()) -> str:
    """Besedilo (napaka, naslov skladbe) z vsakim naslovom samo kot gostitelj (prikaz_naslova) - za zaslon in druge
    naprave (pregled 46, Ö2, Ö8: napaka »unknown url type: 'http://...'« je nosila cel naslov z geslom).
    Pri besedilu napake (`napaka`; pregled 51, Ê5, pregled 57, Ş5): najprej tocno ujemanje znanih skrivnosti vira
    (`tajno`, skrivnosti_naslova), nato naslov s shemo do presledka (tudi z ' ali " v geslu), nazadnje cilj brez sheme
    (_zakrij_cilje). Pri naslovu skladbe to ne velja (v njem so navednice in »&« lahko navadno besedilo)."""
    besedilo = str(besedilo or "")
    if not napaka:
        return _NASLOV_V_BESEDILU.sub(lambda m: prikaz_naslova(m.group(0)), besedilo)
    for t in sorted({str(t) for t in (tajno or ()) if len(str(t)) >= 3}, key=len, reverse=True):
        besedilo = besedilo.replace(t, "…")
    besedilo = _NASLOV_V_NAPAKI.sub(lambda m: prikaz_naslova(m.group(0)), besedilo)
    return _zakrij_cilje(besedilo)


def sporocilo_napake(izjema: object, naslov: object, oznacen: bool = False, najvec: int = 180) -> str:
    """Besedilo izjeme pri branju vira za zaslon in media.json: ZAKRITO, sele nato skrajsano (pregled 57, Ş5: rez na 180
    znakov pred zakrivanjem je odrezal zakljucno navednico in pot z geslom je ostala). Skrivnosti vira zakrijemo po
    tocnem ujemanju samo za vir, ki ni pozitivno znan javen."""
    tajno = skrivnosti_naslova(naslov) if za_ozji_krog(naslov, oznacen) else ()
    zakrito = zakrij_naslove(str(izjema or ""), napaka=True, tajno=tajno)
    return re.sub(r"\s+", " ", zakrito).strip()[:najvec]


def vir_seznama_za(vir: object, ozji: bool = False) -> str:
    """Polje »vir« seznama predvajanja za drugo napravo (pregled 46, Ö2): ozjemu krogu nespremenjeno, drugim samo kratka
    oznaka (YouTube, Spotify ...) - ce je v njem naslov, samo gostitelj (prikaz_naslova; seznam z druge naprave ima
    lahko v viru naslov seznama z geslom)."""
    vir = str(vir or "")
    if ozji:
        return vir
    if len(vir) <= 80 and vir.isprintable() and not any(z in vir for z in "/:@?=&%#\\"):
        return vir
    return prikaz_naslova(vir)


def skladba_za(s: object, ozji: bool = False) -> object:
    """Skladba seznama za drugo napravo: brez prijave streznika (cista_skladba). Napravi zunaj ozjega kroga samo
    pozitivno javna polja (pregled 46, Ö1, Ö2): tok samo znan javen (znan_javen), slika in ozadje samo z znanih javnih
    gostiteljev (javna_slika), zapis Androida samo brez racuna (zapis_androida_javen), naslov ali izvajalec z naslovom
    v besedilu samo z gostiteljem."""
    cista = cista_skladba(s)
    if ozji or not isinstance(cista, dict):
        return cista
    izid = {k: v for k, v in cista.items() if not (k == "url" and not znan_javen(v))}
    for polje in ("slika", "ozadje"):
        if izid.get(polje) and not javna_slika(izid[polje]):
            del izid[polje]
    if "android" in izid and not zapis_androida_javen(izid["android"]):
        del izid["android"]
    for polje in ("naslov", "izvajalec"):
        if isinstance(izid.get(polje), str) and "://" in izid[polje]:
            izid[polje] = zakrij_naslove(izid[polje])
    return izid


def cista_skladba(s: object) -> object:
    """Skladba seznama (ali opis police) brez prijave v `url`, `slika` in `ozadje`. Ce je bila prijava odstranjena,
    dobi oznako `prijava`: Medijski center jo ob predvajanju doda s streznika (MediaCenter.s_prijavo)."""
    if not isinstance(s, dict):
        return s
    izid = dict(s)
    for polje in ("url", "slika", "ozadje"):
        if isinstance(izid.get(polje), str) and izid[polje]:
            cist = brez_prijave(izid[polje])
            if cist != izid[polje]:
                izid[polje] = cist
                izid["prijava"] = True
    return izid
