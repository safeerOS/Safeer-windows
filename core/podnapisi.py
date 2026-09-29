"""Podnapisi ob videih: katere datoteke sodijo k videu, v katerem jeziku so in pretvorba v WebVTT.

Uporabljajo ga strežnik datotek (Safeer Control deli video skupaj z njegovimi podnapisi), magnet
povezave (podnapisi v istem torrentu) in spletni predvajalnik Safeer OS, ki zna samo WebVTT.

Pravila, kateri podnapisi sodijo k videu (kot pri VLC):
- ista mapa in ime se začne z imenom videa brez končnice (``Film.srt``, ``Film.en.srt``, ``Film_English.srt``);
- podmapa ``Subs``/``Subtitles``/``Podnapisi`` z enakim imenom ali z imenom podmape videa;
- kadar je v mapi en sam video, sodijo k njemu vsi podnapisi te mape in podmape s podnapisi.
"""
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

PRIPONE: Dict[str, str] = {
    ".srt": "application/x-subrip",
    ".vtt": "text/vtt",
    ".ass": "text/x-ssa",
    ".ssa": "text/x-ssa",
}
MAPE_PODNAPISOV = {"subs", "sub", "subtitles", "subtitle", "podnapisi"}
#: Podnapisi so besedilo; večja datoteka ni podnapis (in je ne beremo v pomnilnik).
NAJVEC_BAJTOV = 8 * 1024 * 1024

# Pogosta imena jezikov v imenih datotek -> ISO 639-1.
_JEZIKI = {
    "sl": "sl", "slv": "sl", "slo": "sl", "slovenian": "sl", "slovene": "sl", "slovensko": "sl", "slovenscina": "sl", "slovenščina": "sl",
    "en": "en", "eng": "en", "english": "en", "angleski": "en",
    "de": "de", "deu": "de", "ger": "de", "german": "de", "deutsch": "de", "nemski": "de",
    "hr": "hr", "hrv": "hr", "croatian": "hr", "hrvatski": "hr",
    "sr": "sr", "srp": "sr", "scc": "sr", "serbian": "sr", "srpski": "sr",
    "bs": "bs", "bos": "bs", "bosnian": "bs",
    "it": "it", "ita": "it", "italian": "it", "italiano": "it",
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr", "francais": "fr", "français": "fr",
    "es": "es", "spa": "es", "spanish": "es", "espanol": "es", "español": "es",
    "pt": "pt", "por": "pt", "portuguese": "pt",
    "hu": "hu", "hun": "hu", "hungarian": "hu", "magyar": "hu",
    "cs": "cs", "cze": "cs", "ces": "cs", "czech": "cs",
    "pl": "pl", "pol": "pl", "polish": "pl",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "nl": "nl", "dut": "nl", "nld": "nl", "dutch": "nl",
    "mk": "mk", "mkd": "mk", "mac": "mk", "macedonian": "mk",
}
_ZASTAVICE = {"forced", "sdh", "cc", "hi", "default", "full"}


def je_podnapis(ime: str) -> bool:
    return os.path.splitext(str(ime))[1].lower() in PRIPONE


def mime(ime: str) -> str:
    return PRIPONE.get(os.path.splitext(str(ime))[1].lower(), "text/plain")


def jezik(ime_videa: str, ime_podnapisa: str) -> Tuple[str, str]:
    """(ISO koda ali "", dodatna oznaka) iz imena, npr. ``Film.en.forced.srt`` -> ("en", "forced")."""
    osnova = os.path.splitext(os.path.basename(ime_videa))[0].lower()
    ime = os.path.splitext(os.path.basename(ime_podnapisa))[0]
    ostanek = ime[len(osnova):] if ime.lower().startswith(osnova) else ime
    koda, oznake = "", []
    for del_ in re.split(r"[\s._\-\[\]()]+", ostanek):
        d = del_.lower()
        if not d:
            continue
        if d in _ZASTAVICE:
            oznake.append(d)
        elif not koda and d in _JEZIKI:
            koda = _JEZIKI[d]
    return koda, " ".join(oznake)


def ujemajoci(ime_videa: str, kandidati: Iterable[str], samo_en_video: bool) -> List[str]:
    """Relativne poti podnapisov (``Film.en.srt``, ``Subs/Film.srt``), ki sodijo k videu."""
    osnova = os.path.splitext(os.path.basename(ime_videa))[0].lower()
    izid = []
    for rel in kandidati:
        if not je_podnapis(rel):
            continue
        deli = rel.replace("\\", "/").split("/")
        ime = deli[-1].lower()
        v_podmapi = len(deli) > 1
        if v_podmapi and deli[0].lower() not in MAPE_PODNAPISOV:
            continue
        # Subs/<ime videa>/2_English.srt (pogosto v torrentih)
        podmapa_videa = len(deli) > 2 and deli[1].lower() == osnova
        if ime.startswith(osnova) or podmapa_videa or samo_en_video:
            izid.append(rel)
    # Najprej enaka mapa, nato po imenu.
    return sorted(izid, key=lambda r: (r.count("/"), r.lower()))


def podnapisi_mape(pot_videa: str, najvec: int = 24) -> List[str]:
    """Absolutne poti podnapisov ob videu na disku (skrite datoteke in povezave ven iz mape izpustimo)."""
    mapa = os.path.dirname(os.path.realpath(pot_videa))
    kandidati: List[str] = []
    videov = 0
    try:
        imena = os.listdir(mapa)
    except OSError:
        return []
    from core.link_datoteke import vrsta_datoteke  # brez kroga uvozov ob nalaganju
    for ime in imena:
        if ime.startswith("."):
            continue
        cela = os.path.join(mapa, ime)
        if os.path.isdir(cela) and ime.lower() in MAPE_PODNAPISOV:
            for koren, mape, datoteke in os.walk(cela):
                mape[:] = [m for m in mape if not m.startswith(".")]
                if koren.count(os.sep) - cela.count(os.sep) > 1:
                    continue
                for d in datoteke:
                    if not d.startswith("."):
                        kandidati.append(os.path.relpath(os.path.join(koren, d), mapa).replace(os.sep, "/"))
        elif os.path.isfile(cela):
            if vrsta_datoteke(ime) == "video":
                videov += 1
            else:
                kandidati.append(ime)
    izid = []
    for rel in ujemajoci(os.path.basename(pot_videa), kandidati, videov == 1)[:najvec]:
        cela = os.path.realpath(os.path.join(mapa, rel))
        if not cela.startswith(mapa + os.sep):
            continue
        try:
            if os.path.getsize(cela) <= NAJVEC_BAJTOV:
                izid.append(cela)
        except OSError:
            continue
    return izid


def opis(ime_videa: str, pot_podnapisa: str, id_: str) -> dict:
    koda, oznaka = jezik(ime_videa, pot_podnapisa)
    return {"id": id_, "name": os.path.basename(pot_podnapisa), "lang": koda, "label": oznaka,
            "mime": mime(pot_podnapisa)}


# ------------------------------------------------------------------ pretvorba v WebVTT

_CAS_SRT = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def _besedilo(podatki: bytes) -> str:
    for kodiranje in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return podatki.decode(kodiranje)
        except UnicodeDecodeError:
            continue
    return podatki.decode("utf-8", "replace")


def _srt_cas(u: int, m: int, s: int, ms: int) -> str:
    return "%02d:%02d:%02d,%03d" % (u, m, s, ms)


def srt_pocisti(podatki: bytes) -> str:
    """Popravljen SRT v UTF-8, kot ga zna prebrati vsak predvajalnik (VLC je strpen, GStreamer in ExoPlayer ne):
    zaporedne številke znova, brez presledkov za številko, časi z vejico, kodiranje (npr. Windows-1250) v UTF-8."""
    izid, n = [], 0
    for blok in re.split(r"\n\s*\n", _besedilo(podatki).replace("\r\n", "\n").replace("\r", "\n").strip()):
        deli = blok.split("\n")
        i = next((k for k, v in enumerate(deli) if "-->" in v), -1)
        if i < 0:
            continue
        casa = _CAS_SRT.findall(deli[i])
        if len(casa) < 2:
            continue
        a, b = casa[0], casa[1]
        besedilo = [v.rstrip() for v in deli[i + 1:] if v.strip()]
        if not besedilo:
            continue
        n += 1
        izid.append("%d\n%s --> %s\n%s\n" % (
            n, _srt_cas(int(a[0]), int(a[1]), int(a[2]), int(a[3].ljust(3, "0"))),
            _srt_cas(int(b[0]), int(b[1]), int(b[2]), int(b[3].ljust(3, "0"))), "\n".join(besedilo)))
    return "\n".join(izid)


def pocisti(ime: str, podatki: bytes) -> Tuple[str, str]:
    """(končnica, besedilo UTF-8) za predvajalnik: SRT popravimo, druge zapise le prekodiramo."""
    k = os.path.splitext(ime)[1].lower()
    if k in (".ass", ".ssa", ".vtt"):
        return k, _besedilo(podatki)
    return ".srt", srt_pocisti(podatki)


def pripravi(uri: str, ime: str = "", mapa: str = "") -> str:
    """Prenese podnapis (lokalna datoteka ali naš lokalni tok 127.0.0.1) in vrne file:// popravljene kopije.

    Ob napaki vrne izvirni naslov - predvajalnik ga poskusi prebrati sam."""
    import hashlib
    import urllib.parse
    import urllib.request
    try:
        u = urllib.parse.urlsplit(uri)
        if u.scheme == "file":
            pot = urllib.request.url2pathname(u.path)
            if os.path.getsize(pot) > NAJVEC_BAJTOV:
                return uri
            with open(pot, "rb") as d:
                podatki = d.read()
        elif u.scheme == "http" and u.hostname == "127.0.0.1":
            # Brez sistemskega posrednika: skrivni naslov lokalnega toka ne sme na proxy.
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(uri, timeout=60) as o:
                podatki = o.read(NAJVEC_BAJTOV + 1)
            if len(podatki) > NAJVEC_BAJTOV:
                return uri
        else:
            return uri
        koncnica, besedilo = pocisti(ime or u.path, podatki)
        mapa = mapa or os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safeer-os", "podnapisi")
        os.makedirs(mapa, exist_ok=True)
        cilj = os.path.join(mapa, hashlib.sha256(uri.encode()).hexdigest()[:24] + koncnica)
        if koncnica == ".srt":
            # GStreamer (1.24) SRT z vrsticami LF ne prepozna kot podnapisov, s CRLF pa ga - preverjeno 29. 9. 2026.
            besedilo = besedilo.replace("\r\n", "\n").replace("\n", "\r\n")
        with open(cilj + ".tmp", "w", encoding="utf-8", newline="") as d:
            d.write(besedilo)
        os.replace(cilj + ".tmp", cilj)
        return "file://" + urllib.request.pathname2url(cilj)
    except Exception as e:  # noqa: BLE001 - brez popravka predvajalnik prebere izvirnik
        print("[SafeerOS] podnapis ni pripravljen:", os.path.basename(ime or uri), type(e).__name__, e, flush=True)
        return uri


def _vtt_cas(u: int, m: int, s: int, ms: int) -> str:
    return "%02d:%02d:%02d.%03d" % (u, m, s, ms)


def srt_v_vtt(podatki: bytes) -> str:
    vrstice = ["WEBVTT", ""]
    for blok in re.split(r"\r?\n\s*\r?\n", _besedilo(podatki).replace("\r\n", "\n").strip()):
        deli = [v for v in blok.split("\n")]
        i = next((k for k, v in enumerate(deli) if "-->" in v), -1)
        if i < 0:
            continue
        casa = _CAS_SRT.findall(deli[i])
        if len(casa) < 2:
            continue
        a, b = casa[0], casa[1]
        vrstice.append("%s --> %s" % (_vtt_cas(int(a[0]), int(a[1]), int(a[2]), int(a[3].ljust(3, "0"))),
                                       _vtt_cas(int(b[0]), int(b[1]), int(b[2]), int(b[3].ljust(3, "0")))))
        vrstice.extend(_varno_besedilo(v) for v in deli[i + 1:] if v.strip())
        vrstice.append("")
    return "\n".join(vrstice) + "\n"


def _varno_besedilo(v: str) -> str:
    """Obdrži <i>, <b>, <u>; vse drugo (tudi <font>) odstrani - WebVTT ne sme dobiti poljubnega HTML."""
    v = re.sub(r"\{\\[^}]*\}", "", v)
    v = re.sub(r"<(?!/?[ibu]>)[^>]*>", "", v)
    return v.replace("-->", "->")


def ass_v_vtt(podatki: bytes) -> str:
    vrstice = ["WEBVTT", ""]
    oblika: List[str] = []
    v_dogodkih = False
    for v in _besedilo(podatki).splitlines():
        s = v.strip()
        if s.startswith("["):
            v_dogodkih = s.lower() == "[events]"
            continue
        if not v_dogodkih:
            continue
        if s.lower().startswith("format:"):
            oblika = [p.strip().lower() for p in s[7:].split(",")]
            continue
        if not s.lower().startswith("dialogue:") or not oblika:
            continue
        polja = s[9:].split(",", len(oblika) - 1)
        if len(polja) < len(oblika):
            continue
        z = dict(zip(oblika, polja))
        a, b = _ass_cas(z.get("start", "")), _ass_cas(z.get("end", ""))
        if a is None or b is None:
            continue
        besedilo = re.sub(r"\{[^}]*\}", "", z.get("text", "")).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
        besedilo = "\n".join(_varno_besedilo(x) for x in besedilo.split("\n") if x.strip())
        if not besedilo:
            continue
        vrstice += ["%s --> %s" % (a, b), besedilo, ""]
    return "\n".join(vrstice) + "\n"


def _ass_cas(t: str) -> Optional[str]:
    m = re.match(r"\s*(\d+):(\d{2}):(\d{2})[.:](\d{1,2})", t)
    if not m:
        return None
    return _vtt_cas(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4).ljust(2, "0")) * 10)


def v_vtt(ime: str, podatki: bytes) -> str:
    k = os.path.splitext(ime)[1].lower()
    if k == ".vtt":
        t = _besedilo(podatki)
        return t if t.lstrip("﻿").startswith("WEBVTT") else "WEBVTT\n\n" + t
    if k in (".ass", ".ssa"):
        return ass_v_vtt(podatki)
    return srt_v_vtt(podatki)


# ------------------------------------------------------------------ izbira uporabnika

def _pot_nastavitev() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "safeer-os", "podnapisi.json")


def nalozi_nastavitve() -> dict:
    """{"izklop": None|bool, "jezik": ""} - None pomeni samodejno (kot VLC)."""
    import json
    try:
        with open(_pot_nastavitev(), encoding="utf-8") as d:
            n = json.load(d)
        izklop = n.get("izklop")
        return {"izklop": izklop if isinstance(izklop, bool) else None, "jezik": str(n.get("jezik") or "")[:8]}
    except (OSError, ValueError, AttributeError):
        return {"izklop": None, "jezik": ""}


def shrani_nastavitve(n: dict) -> None:
    import json
    pot = _pot_nastavitev()
    try:
        os.makedirs(os.path.dirname(pot), exist_ok=True)
        with open(pot + ".tmp", "w", encoding="utf-8") as d:
            json.dump({"izklop": n.get("izklop"), "jezik": str(n.get("jezik") or "")[:8]}, d)
        os.replace(pot + ".tmp", pot)
    except OSError:
        pass


def jezik_sistema() -> str:
    import locale
    for ime in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(ime, "")
        if v and v not in ("C", "POSIX"):
            return v.split(":")[0][:2].lower()
    try:
        return (locale.getlocale()[0] or "")[:2].lower()
    except ValueError:
        return ""


_IMENA = {
    "sl": {"sl": "slovenščina", "en": "angleščina", "de": "nemščina", "hr": "hrvaščina", "sr": "srbščina", "bs": "bosanščina",
           "it": "italijanščina", "fr": "francoščina", "es": "španščina", "pt": "portugalščina", "hu": "madžarščina",
           "cs": "češčina", "pl": "poljščina", "ru": "ruščina", "nl": "nizozemščina", "mk": "makedonščina"},
    "en": {"sl": "Slovenian", "en": "English", "de": "German", "hr": "Croatian", "sr": "Serbian", "bs": "Bosnian",
           "it": "Italian", "fr": "French", "es": "Spanish", "pt": "Portuguese", "hu": "Hungarian", "cs": "Czech",
           "pl": "Polish", "ru": "Russian", "nl": "Dutch", "mk": "Macedonian"},
    "de": {"sl": "Slowenisch", "en": "Englisch", "de": "Deutsch", "hr": "Kroatisch", "sr": "Serbisch", "bs": "Bosnisch",
           "it": "Italienisch", "fr": "Französisch", "es": "Spanisch", "pt": "Portugiesisch", "hu": "Ungarisch",
           "cs": "Tschechisch", "pl": "Polnisch", "ru": "Russisch", "nl": "Niederländisch", "mk": "Mazedonisch"},
    "es": {"sl": "esloveno", "en": "inglés", "de": "alemán", "hr": "croata", "sr": "serbio", "bs": "bosnio", "it": "italiano",
           "fr": "francés", "es": "español", "pt": "portugués", "hu": "húngaro", "cs": "checo", "pl": "polaco", "ru": "ruso",
           "nl": "neerlandés", "mk": "macedonio"},
    "fr": {"sl": "slovène", "en": "anglais", "de": "allemand", "hr": "croate", "sr": "serbe", "bs": "bosnien", "it": "italien",
           "fr": "français", "es": "espagnol", "pt": "portugais", "hu": "hongrois", "cs": "tchèque", "pl": "polonais",
           "ru": "russe", "nl": "néerlandais", "mk": "macédonien"},
    "it": {"sl": "sloveno", "en": "inglese", "de": "tedesco", "hr": "croato", "sr": "serbo", "bs": "bosniaco", "it": "italiano",
           "fr": "francese", "es": "spagnolo", "pt": "portoghese", "hu": "ungherese", "cs": "ceco", "pl": "polacco",
           "ru": "russo", "nl": "olandese", "mk": "macedone"},
}


def ime_jezika(koda: str, jezik_vmesnika: str = "sl") -> str:
    ime = _IMENA.get(jezik_vmesnika, _IMENA["en"]).get(str(koda or "")[:2].lower(), str(koda or ""))
    return ime[:1].upper() + ime[1:]
