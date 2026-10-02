"""Usklajevanje seznamov predvajanja med napravami v Safeer Linku - cista pravila (brez omrezja in diska).

Enaka kot v Safeer OS za Android (SeznamiPravila.kt): seznam je dolocen z imenom, velja zadnja sprememba (`cas`, ms).
Izbris si naprava zapomni s casom, da se seznam ne vrne z naprave, ki ga se ima. Nic ne gre v oblak.

Protokol (ukaz `lists.get` po Safeer Linku):
  {}            -> {"lists": [{"ime", "vir", "cas", "stevilo"}], "deleted": {ime: cas}}
  {"ime", "od"} -> {"ime", "vir", "cas", "stevilo", "od", "skladbe": [najvec STRAN]}   (sporocila Linka so omejena)
Skladba: {"naslov", "izvajalec", "youtube", "sekund", "slika"} in po potrebi "url", "video", "android" (poln zapis
naprave Android, ki ga racunalnik le prenese naprej).
"""
from __future__ import annotations

from typing import Callable, Optional

DEJANJE = "lists.get"
STRAN = 100
NIC, PREVZEMI, ZDRUZI = "nic", "prevzemi", "zdruzi"


def kljuc(s: dict) -> str:
    """Ista skladba: izvajalec in naslov; brez njiju posnetek ali naslov datoteke."""
    naslov = str(s.get("naslov") or "").strip().lower()
    if naslov:
        return "n:" + str(s.get("izvajalec") or "").strip().lower() + "|" + naslov
    if s.get("youtube"):
        return "yt:" + str(s["youtube"])
    return "u:" + str(s.get("url") or "")


def korak(moj: Optional[tuple], izbrisan: int, tuj: tuple) -> str:
    """Kaj storiti s seznamom druge naprave. moj/tuj = (cas, stevilo); moj None = seznama tukaj ni; izbrisan = kdaj
    smo ga tu izbrisali (0 = nikoli). Novejsi zmaga; ob enakem casu in razlicnem stevilu skladb zdruzimo."""
    tuj_cas, tuj_stevilo = int(tuj[0] or 0), int(tuj[1] or 0)
    if tuj_stevilo <= 0:
        return NIC
    if moj is None:
        return NIC if izbrisan > 0 and izbrisan >= tuj_cas else PREVZEMI
    moj_cas, moj_stevilo = int(moj[0] or 0), int(moj[1] or 0)
    if tuj_cas > moj_cas:
        return PREVZEMI
    if tuj_cas == moj_cas and tuj_stevilo != moj_stevilo:
        return ZDRUZI
    return NIC


def nov_cas(zdaj: int, prej: int = 0, izbrisan: int = 0) -> int:
    """Cas nove krajevne spremembe ali izbrisa: nikoli starejsi od prejsnjega stanja seznama in od znanega izbrisa.
    Ure naprav niso enake - brez tega bi naprava z zaostalo uro spremenila seznam »v preteklosti« in bi druga naprava
    njeno spremembo prezrla ali znova uveljavila star izbris (enako SeznamiPravila.novCas na Androidu)."""
    return max(int(zdaj), int(prej or 0) + 1, int(izbrisan or 0) + 1)


def izbris_velja(moj_cas: int, cas_izbrisa: int) -> bool:
    """Izbris na drugi napravi velja tudi tukaj, ce seznama od takrat nismo spremenili."""
    return cas_izbrisa > 0 and cas_izbrisa >= int(moj_cas or 0)


def zdruzi(moje: list, tuje: list, najvec: int) -> list:
    """Moje skladbe in za njimi tuje, ki jih se nimam."""
    imam = {kljuc(s) for s in moje}
    izid = list(moje)
    for s in tuje:
        k = kljuc(s)
        if k not in imam:
            imam.add(k)
            izid.append(s)
    return izid[:najvec]


def prevzemi(moje: list, tuje: list, najvec: int) -> list:
    """Tuje skladbe; posnetek, ki smo ga za isto skladbo tukaj ze nasli (tuja ga se nima), ostane."""
    znani = {kljuc(s): s for s in moje if s.get("youtube")}
    izid, videni = [], set()
    for t in tuje:
        k = kljuc(t)
        if k in videni:
            continue
        videni.add(k)
        m = znani.get(k) if not t.get("youtube") and not t.get("url") else None
        if m:
            t = dict(t, youtube=m["youtube"], slika=m.get("slika") or t.get("slika") or "")
        izid.append(t)
    return izid[:najvec]


def cista_skladba(s: object) -> Optional[dict]:
    """Skladba z druge naprave: samo znana polja pravih vrst (nic drugega ne shranimo)."""
    if not isinstance(s, dict):
        return None
    naslov = str(s.get("naslov") or "")[:300]
    yt = str(s.get("youtube") or "")
    url = str(s.get("url") or "")
    if yt and not all(c.isalnum() or c in "_-" for c in yt):
        yt = ""
    if url and not url.startswith(("https://", "http://")):
        url = ""
    if not naslov and not yt and not url:
        return None
    izid = {"naslov": naslov, "izvajalec": str(s.get("izvajalec") or "")[:300], "youtube": yt[:20],
            "slika": str(s.get("slika") or "")[:600] if str(s.get("slika") or "").startswith(("https://", "http://")) else "",
            "sekund": int(s.get("sekund") or 0) if isinstance(s.get("sekund"), (int, float)) else 0}
    if url:
        izid["url"] = url[:1000]
    if s.get("video") is True:
        izid["video"] = True
    if isinstance(s.get("android"), str) and len(s["android"]) < 4000:
        izid["android"] = s["android"]
    return izid


def prevzemi_od(vprasaj: Callable[[dict], Optional[dict]], seznami: list, izbrisani: dict, najvec: int) -> tuple:
    """Prevzame novejse sezname in izbrise ene naprave. vprasaj(parametri) poslje `lists.get` in vrne `data` ali None.
    Vrne (novi seznami, novi izbrisani, ali se je kaj spremenilo)."""
    kazalo = vprasaj({})
    if not isinstance(kazalo, dict):
        return seznami, izbrisani, False
    seznami = [dict(x) for x in seznami]
    izbrisani = dict(izbrisani)
    spremenjeno = False
    tuji_izbrisi = kazalo.get("deleted") if isinstance(kazalo.get("deleted"), dict) else {}
    for ime, cas in list(tuji_izbrisi.items())[:200]:
        if not isinstance(cas, (int, float)) or not isinstance(ime, str):
            continue
        cas = int(cas)
        moj = next((x for x in seznami if x.get("ime") == ime), None)
        if moj is None:
            if cas > int(izbrisani.get(ime) or 0):
                izbrisani[ime] = cas
        elif izbris_velja(int(moj.get("cas") or 0), cas):
            seznami = [x for x in seznami if x.get("ime") != ime]
            izbrisani[ime] = max(cas, int(izbrisani.get(ime) or 0))
            spremenjeno = True
    for g in (kazalo.get("lists") if isinstance(kazalo.get("lists"), list) else [])[:60]:
        if not isinstance(g, dict) or not str(g.get("ime") or "").strip():
            continue
        ime = str(g["ime"])[:60]
        tuj = (int(g.get("cas") or 0), int(g.get("stevilo") or 0))
        moj = next((x for x in seznami if x.get("ime") == ime), None)
        k = korak((int(moj.get("cas") or 0), len(moj.get("skladbe") or [])) if moj else None, int(izbrisani.get(ime) or 0), tuj)
        if k == NIC:
            continue
        tuje, od, cel = [], 0, True
        while od < tuj[1] and od < najvec:
            stran = vprasaj({"ime": ime, "od": od})
            skladbe = stran.get("skladbe") if isinstance(stran, dict) else None
            if not isinstance(skladbe, list):
                cel = False        # naprava vmes ni odgovorila: napol prenesenega seznama ne shranimo
                break
            if not skladbe:
                break
            tuje += [c for c in (cista_skladba(s) for s in skladbe) if c]
            od += len(skladbe)
        if not cel or not tuje:
            continue
        moje = [s for s in (moj.get("skladbe") or []) if isinstance(s, dict)] if moj else []
        nove = prevzemi(moje, tuje, najvec) if k == PREVZEMI else zdruzi(moje, tuje, najvec)
        nov = {"ime": ime, "vir": str(g.get("vir") or (moj or {}).get("vir") or "")[:40], "cas": tuj[0], "skladbe": nove}
        seznami = [nov if x.get("ime") == ime else x for x in seznami] if moj else [nov] + seznami
        izbrisani.pop(ime, None)
        spremenjeno = True
    return seznami, izbrisani, spremenjeno
