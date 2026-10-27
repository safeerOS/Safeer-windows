"""Datoteke za Safeer OS na Linuxu: uporabnikove mape, pregled mape, iskanje in odpiranje.

Datoteke odpira program, ki ga ima uporabnik v Mintu nastavljenega za to vrsto (xdg-open /
Gio), mape pa Nemo, ce zeli vec, kot pokaze Safeer OS. Ustvari mapo ali datoteko in preimenuje
na uporabnikovo zahtevo; nicesar ne prepise, brisanje gre samo v Smeti.
"""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from collections import deque
from typing import List, Optional

from core import zasebni_webkit
from core.iskalni_kljuc import kljuc as kljuc_imena  # isti kljuc kot zapiski in medijska knjiznica

NAJVEC_V_MAPI = 5000
NAJVEC_ZADETKOV = 60

#: Uporabnikove mape XDG v vrstnem redu, kot jih pokaze Safeer OS.
MAPE = ("DESKTOP", "DOCUMENTS", "DOWNLOAD", "PICTURES", "MUSIC", "VIDEOS")
PRIVZETO = {"DESKTOP": "Desktop", "DOCUMENTS": "Documents", "DOWNLOAD": "Downloads", "PICTURES": "Pictures",
            "MUSIC": "Music", "VIDEOS": "Videos"}


def uporabniske_mape(dom: Optional[str] = None) -> List[dict]:
    dom = dom or os.path.expanduser("~")
    nastavljene = {}
    try:
        with open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(dom, ".config"),
                               "user-dirs.dirs"), encoding="utf-8") as f:
            for vrstica in f:
                m = re.match(r'\s*XDG_([A-Z]+)_DIR="(.*)"\s*$', vrstica)
                if m:
                    nastavljene[m.group(1)] = m.group(2).replace("$HOME", dom)
    except Exception:
        pass
    izhod = [{"vrsta": "HOME", "pot": dom, "ime": os.path.basename(dom)}]
    for vrsta in MAPE:
        pot = nastavljene.get(vrsta) or os.path.join(dom, PRIVZETO[vrsta])
        if os.path.isdir(pot) and os.path.realpath(pot) != os.path.realpath(dom):
            izhod.append({"vrsta": vrsta, "pot": pot, "ime": os.path.basename(pot.rstrip("/"))})
    return izhod


def zaznamki(dom: Optional[str] = None, izpusti: Optional[List[str]] = None) -> List[dict]:
    """Zaznamki map, kot jih uporabnik vidi v Nemu (~/.config/gtk-3.0/bookmarks): samo krajevne mape, ki obstajajo,
    brez tistih, ki so ze med uporabnikovimi mapami (lastnik, 11. 10. 2026: pri obicajni temi jih ima pri roki)."""
    dom = dom or os.path.expanduser("~")
    znane = {os.path.realpath(p) for p in (izpusti or [])}
    izhod, videne = [], set()
    pot_datoteke = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(dom, ".config"), "gtk-3.0", "bookmarks")
    try:
        with open(pot_datoteke, encoding="utf-8") as f:
            vrstice = f.read().splitlines()
    except Exception:
        return izhod
    for vrstica in vrstice[:50]:
        uri, _, ime = vrstica.strip().partition(" ")
        if not uri.startswith("file://"):
            continue
        pot = urllib.parse.unquote(urllib.parse.urlsplit(uri).path)
        prava = os.path.realpath(pot)
        if not pot or not os.path.isdir(pot) or prava in znane or prava in videne:
            continue
        videne.add(prava)
        izhod.append({"vrsta": "ZAZNAMEK", "pot": pot, "ime": ime.strip() or os.path.basename(pot.rstrip("/")) or pot})
    return izhod


def vrsta_datoteke(ime: str, je_mapa: bool = False) -> str:
    """Groba vrsta za ikono na strani: mapa, slika, video, zvok, dokument, arhiv, program, drugo."""
    if je_mapa:
        return "mapa"
    mime = mimetypes.guess_type(ime)[0] or ""
    if mime.startswith("image/"):
        return "slika"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "zvok"
    konc = os.path.splitext(ime)[1].lower()
    if konc in (".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".zst", ".deb"):
        return "arhiv"
    if konc in (".appimage", ".sh", ".run", ".exe"):
        return "program"
    if mime.startswith("text/") or konc in (".pdf", ".odt", ".ods", ".odp", ".doc", ".docx", ".xls", ".xlsx",
                                            ".ppt", ".pptx", ".md", ".rtf", ".epub", ".json", ".csv"):
        return "dokument"
    return "drugo"


def _element(pot: str, ime: str) -> Optional[dict]:
    try:
        st = os.stat(pot)
    except OSError:
        return None
    je_mapa = os.path.isdir(pot)
    return {"ime": ime, "pot": pot, "mapa": je_mapa, "velikost": 0 if je_mapa else st.st_size,
            "spremenjeno": st.st_mtime, "vrsta": vrsta_datoteke(ime, je_mapa)}


def preglej(pot: str, skrite: bool = False) -> dict:
    """Vsebina mape: mape najprej, nato datoteke; oboje po abecedi."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "~")))
    if not os.path.isdir(pot):
        return {"pot": pot, "napaka": "ni_mape", "elementi": []}
    try:
        imena = os.listdir(pot)
    except PermissionError:
        return {"pot": pot, "napaka": "ni_dovoljenja", "elementi": []}
    except OSError:
        return {"pot": pot, "napaka": "ni_mape", "elementi": []}
    elementi = []
    for ime in imena:
        if not skrite and ime.startswith("."):
            continue
        e = _element(os.path.join(pot, ime), ime)
        if e is not None:
            elementi.append(e)
    elementi.sort(key=lambda e: (not e["mapa"], e["ime"].lower()))
    stars = os.path.dirname(pot) if pot != "/" else ""
    return {"pot": pot, "stars": stars, "napaka": "", "skupaj": len(elementi),
            "elementi": elementi[:NAJVEC_V_MAPI]}


#: Mape, v katerih so datoteke programov, ne uporabnikove (iskanje jih preskoci).
PRESKOCI = {"node_modules", "__pycache__", "snap", "site-packages", "dist-packages", "venv", ".venv", "build", "dist",
            "Applications", "go", "resources", "target", "vendor"}


def isci(niz: str, dom: Optional[str] = None, rok: float = 1.5) -> List[dict]:
    """Datoteke in mape v domaci mapi, katerih ime vsebuje vse besede niza (brez sumnikov): najprej plitve (po
    sirini), brez skritih in brez map s programsko kodo; najvec 1,5 s. To je hoja po disku - Safeer OS isce z
    indeksom (core/os_iskalnik.py), ta ostane za cas, ko indeksa se ni, in za tisto, kar vanj ni slo."""
    if len(str(niz or "").strip()) < 2:
        return []
    besede = kljuc_imena(niz).split()
    dom = dom or os.path.expanduser("~")
    konec = time.monotonic() + rok
    zadetki: List[dict] = []
    vrsta = deque([dom])
    while vrsta and time.monotonic() < konec:
        mapa = vrsta.popleft()
        try:
            vnosi = sorted(os.scandir(mapa), key=lambda v: v.name.lower())
        except OSError:
            continue
        for v in vnosi:
            if v.name.startswith("."):
                continue
            try:
                je_mapa = v.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if je_mapa and v.name not in PRESKOCI:
                vrsta.append(v.path)
            ime = kljuc_imena(v.name)
            if all(b in ime for b in besede):
                e = _element(v.path, v.name)
                if e is not None:
                    zadetki.append(e)
                    if len(zadetki) >= NAJVEC_ZADETKOV:
                        return zadetki
    return zadetki


#: Malo prostora: manj kot 10 % diska ali manj kot 5 GB (kar nastopi prej).
MALO_DELEZ = 0.10
MALO_BAJTOV = 5 * 1024 ** 3
#: Najmanjsa datoteka, ki jo ponudimo za shranjevanje na drugo napravo.
NAJMANJ_VELIKA = 100 * 1024 ** 2


def prostor(dom: Optional[str] = None) -> dict:
    """Prostor na disku domace mape (takoj, brez pregledovanja): skupaj, prosto in ali ga je malo."""
    try:
        st = os.statvfs(dom or os.path.expanduser("~"))
    except OSError:
        return {"skupaj": 0, "prosto": -1, "malo": False}
    skupaj, prosto = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    return {"skupaj": skupaj, "prosto": prosto, "malo": prosto < MALO_BAJTOV or (skupaj > 0 and prosto < skupaj * MALO_DELEZ)}


def najvecje(dom: Optional[str] = None, koliko: int = 12, rok: float = 1.5) -> List[dict]:
    """Najvecje datoteke v domaci mapi (vsaj 100 MB), za shranjevanje na drugo napravo v Linku.
    Kot isci(): brez skritih map in map s programsko kodo, najvec `rok` sekund - brez opaznega zastoja."""
    dom = dom or os.path.expanduser("~")
    konec = time.monotonic() + rok
    najdene: List[tuple] = []
    vrsta = deque([dom])
    while vrsta and time.monotonic() < konec:
        mapa = vrsta.popleft()
        try:
            vnosi = list(os.scandir(mapa))
        except OSError:
            continue
        for v in vnosi:
            if v.name.startswith("."):
                continue
            try:
                if v.is_dir(follow_symlinks=False):
                    if v.name not in PRESKOCI:
                        vrsta.append(v.path)
                elif v.is_file(follow_symlinks=False):
                    velikost = v.stat(follow_symlinks=False).st_size
                    if velikost >= NAJMANJ_VELIKA:
                        najdene.append((velikost, v.path, v.name))
            except OSError:
                continue
    najdene.sort(reverse=True)
    izid = []
    for _, pot, ime in najdene[:koliko]:
        e = _element(pot, ime)
        if e is not None:
            izid.append(e)
    return izid


def odpri(pot: str) -> bool:
    """Odpre datoteko s privzetim programom oz. mapo v Nemu."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.exists(pot):
        return False
    from core import varuh_procesov
    for ukaz in (["gio", "open", pot], ["xdg-open", pot]):
        if shutil.which(ukaz[0]) is None:
            continue
        try:
            pid = varuh_procesov.zazeni_program(ukaz, zasebni_webkit.okolje_za_zunanje())
            if pid:
                return True
        except Exception:
            pass
    # V procesu (Gio), brez skripte xdg-open in procesa gio (meritev v commitu 19. 10. 2026); ukaza sta rezerva.
    if zasebni_webkit.odpri_privzeto(pot):
        return True
    for ukaz in (["xdg-open", pot], ["gio", "open", pot]):
        if shutil.which(ukaz[0]) is None:
            continue
        try:
            # Privzeti program dobi sistemsko okolje, brez nasih zasebnih poti (core/zasebni_webkit.py).
            subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                             env=zasebni_webkit.okolje_za_zunanje())
            return True
        except Exception:
            continue
    return False


def pokazi_v_mapi(pot: str) -> bool:
    """Odpre Nemo z oznaceno datoteko."""
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if not os.path.exists(pot) or shutil.which("nemo") is None:
        return False
    from core import varuh_procesov
    try:
        pid = varuh_procesov.zazeni_program(["nemo", pot], zasebni_webkit.okolje_za_zunanje())
        if pid:
            return True
    except Exception:
        pass
    try:
        subprocess.Popen(["nemo", pot], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env=zasebni_webkit.okolje_za_zunanje())
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ ustvarjanje (desni klik v Datotekah)
# Kot v Nemu: nova mapa in nova datoteka (prazna, besedilna, dokument/preglednica/predstavitev
# LibreOffice ali predloga iz mape Predloge). Nic obstojecega se ne prepise; brisanje gre v Smeti.

#: Vrste novih datotek: kljuc -> (koncnica, MIME za ODF ali None).
NOVE_VRSTE = {
    "prazna": ("", None),
    "besedilo": (".txt", None),
    "dokument": (".odt", "application/vnd.oasis.opendocument.text"),
    "preglednica": (".ods", "application/vnd.oasis.opendocument.spreadsheet"),
    "predstavitev": (".odp", "application/vnd.oasis.opendocument.presentation"),
}
_ODF_TELO = {
    "application/vnd.oasis.opendocument.text": "<office:text><text:p/></office:text>",
    "application/vnd.oasis.opendocument.spreadsheet":
        "<office:spreadsheet><table:table table:name=\"List1\"><table:table-row><table:table-cell/>"
        "</table:table-row></table:table></office:spreadsheet>",
    "application/vnd.oasis.opendocument.presentation":
        "<office:presentation><draw:page draw:name=\"page1\"/></office:presentation>",
}


def _prosto_ime(mapa: str, ime: str) -> str:
    """Ime, ki v mapi se ne obstaja: »Nova mapa«, »Nova mapa (2)« ..."""
    koren, konc = os.path.splitext(ime) if not os.path.isdir(os.path.join(mapa, ime)) else (ime, "")
    kandidat, n = ime, 2
    while os.path.lexists(os.path.join(mapa, kandidat)):
        kandidat = "%s (%d)%s" % (koren, n, konc)
        n += 1
    return kandidat


def _preveri_mapo(mapa: str) -> str:
    from core import link_urejanje
    mapa = os.path.abspath(os.path.expanduser(str(mapa or "")))
    if not os.path.isdir(mapa):
        raise link_urejanje.NapakaUrejanja("ni_mape")
    if not os.access(mapa, os.W_OK | os.X_OK):
        raise link_urejanje.NapakaUrejanja("ni_dovoljenja")
    return mapa


def _odf(pot: str, mime: str) -> None:
    import zipfile
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" office:version="1.3"')
    vsebina = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content %s><office:body>%s'
               '</office:body></office:document-content>' % (ns, _ODF_TELO[mime]))
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest '
                'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="%s"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>' % mime)
    with zipfile.ZipFile(pot, "x") as z:
        # mimetype mora biti prvi in nestisnjen (specifikacija ODF).
        z.writestr(zipfile.ZipInfo("mimetype"), mime, compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/manifest.xml", manifest, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("content.xml", vsebina, compress_type=zipfile.ZIP_DEFLATED)


def predloge() -> List[dict]:
    """Datoteke iz uporabnikove mape Predloge (XDG TEMPLATES) - kot »Ustvari nov dokument« v Nemu."""
    mapa = ""
    try:
        r = subprocess.run(["xdg-user-dir", "TEMPLATES"], capture_output=True, text=True, timeout=3)
        mapa = r.stdout.strip()
    except Exception:
        pass
    if not mapa or mapa == os.path.expanduser("~") or not os.path.isdir(mapa):
        return []
    izid = []
    for ime in sorted(os.listdir(mapa), key=str.lower)[:40]:
        pot = os.path.join(mapa, ime)
        if not ime.startswith(".") and os.path.isfile(pot):
            izid.append({"ime": os.path.splitext(ime)[0], "pot": pot, "vrsta": vrsta_datoteke(ime)})
    return izid


def ustvari_mapo(mapa: str, ime: str) -> dict:
    """{"ok", "pot"} ali {"ok": False, "napaka"}; obstojecega imena ne prepise (doda (2), (3) ...)."""
    from core import link_urejanje
    try:
        mapa = _preveri_mapo(mapa)
        ime = _prosto_ime(mapa, link_urejanje.varno_ime(ime or "Nova mapa"))
        pot = os.path.join(mapa, ime)
        os.mkdir(pot)
        return {"ok": True, "pot": pot, "ime": ime}
    except link_urejanje.NapakaUrejanja as e:
        return {"ok": False, "napaka": str(e)}
    except OSError:
        return {"ok": False, "napaka": "ni_dovoljenja"}


def ustvari_datoteko(mapa: str, ime: str, vrsta: str = "prazna", predloga: str = "") -> dict:
    """Nova datoteka: prazna, besedilna, prazen dokument ODF ali kopija predloge iz mape Predloge."""
    from core import link_urejanje
    try:
        mapa = _preveri_mapo(mapa)
        ime = link_urejanje.varno_ime(ime or "Nova datoteka")
        if predloga:
            dovoljene = {p["pot"] for p in predloge()}
            if predloga not in dovoljene:
                raise link_urejanje.NapakaUrejanja("ni_predloge")
            konc = os.path.splitext(predloga)[1]
        else:
            konc, mime = NOVE_VRSTE.get(vrsta, NOVE_VRSTE["prazna"])
        if konc and not ime.lower().endswith(konc.lower()):
            ime += konc
        ime = _prosto_ime(mapa, ime)
        pot = os.path.join(mapa, ime)
        if predloga:
            with open(predloga, "rb") as v, open(pot, "xb") as c:
                shutil.copyfileobj(v, c)
        elif mime:
            _odf(pot, mime)
        else:
            with open(pot, "x", encoding="utf-8"):
                pass
        return {"ok": True, "pot": pot, "ime": ime}
    except link_urejanje.NapakaUrejanja as e:
        return {"ok": False, "napaka": str(e)}
    except FileExistsError:
        return {"ok": False, "napaka": "obstaja"}
    except OSError:
        return {"ok": False, "napaka": "ni_dovoljenja"}


def preimenuj(pot: str, novo_ime: str) -> dict:
    from core import link_urejanje
    try:
        nova = link_urejanje.preimenuj(os.path.abspath(os.path.expanduser(str(pot or ""))), novo_ime)
        return {"ok": True, "pot": nova}
    except link_urejanje.NapakaUrejanja as e:
        return {"ok": False, "napaka": str(e)}


def v_smeti(pot: str) -> dict:
    """Nikoli trajno: v Smeti, od koder se datoteka obnovi (Nemo -> Smeti)."""
    from core import link_urejanje
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    if pot in ("/", os.path.expanduser("~")):
        return {"ok": False, "napaka": "ni_dovoljeno"}
    zacetek = time.time()
    try:
        link_urejanje.v_smeti(pot)
        return {"ok": True, "id": _id_po_izbrisu(pot, zacetek)}
    except link_urejanje.NapakaUrejanja as e:
        return {"ok": False, "napaka": str(e)}


def _id_po_izbrisu(pot: str, od: float) -> str:
    """Ime, pod katerim je pravkar izbrisana datoteka v domacih Smeteh (za razveljavitev). Prazno, ce je tam ni:
    datoteka z drugega nosilca gre v Smeti tistega nosilca."""
    import urllib.parse
    info = os.path.join(_mapa_smeti(), "info")
    try:
        imena = os.listdir(info)
    except OSError:
        return ""
    najnovejsi, id_ = 0.0, ""
    for ime in imena:
        if not ime.endswith(".trashinfo"):
            continue
        opis = os.path.join(info, ime)
        try:
            cas = os.stat(opis).st_mtime
            if cas < od - 2 or cas < najnovejsi:
                continue
            with open(opis, encoding="utf-8", errors="replace") as f:
                for v in f:
                    if v.startswith("Path=") and urllib.parse.unquote(v[5:].strip()) == pot:
                        najnovejsi, id_ = cas, ime[:-len(".trashinfo")]
        except OSError:
            continue
    return id_


# ====================================================================== upravljanje (kopiraj, premakni, smeti, nosilci)
# Safeer OS ne nadomesca Nema, a osnovna opravila z datotekami morajo biti na voljo tam, kjer uporabnik je:
# kopiraj/premakni, pogled v Smeti z obnovitvijo, nosilci (USB, drugi diski), lastnosti in slicice.

#: Najvec datotek ali map v enem lepljenju (zascita pred pomoto, npr. izbrana cela domaca mapa).
NAJVEC_NAENKRAT = 500


def _koda_napake(e: OSError) -> str:
    import errno
    if e.errno in (errno.ENOSPC, errno.EDQUOT):
        return "ni_prostora"
    if e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return "ni_dovoljenja"
    return "napaka"


def prilepi(viri, cilj_mapa: str, premakni: bool = False) -> dict:
    """Kopira ali premakne datoteke in mape v mapo `cilj_mapa`. Obstojecega nikoli ne prepise (dobi ime »ime (2)«),
    mape ne kopira same vase, domace mape in korena se ne dotakne. Vrne {"ok", "narejeno": [poti], "napake": [...]}."""
    from core import link_urejanje
    try:
        cilj = _preveri_mapo(cilj_mapa)
    except link_urejanje.NapakaUrejanja as e:
        return {"ok": False, "napaka": str(e), "narejeno": [], "napake": []}
    seznam = [os.path.abspath(os.path.expanduser(str(v))) for v in (viri if isinstance(viri, (list, tuple)) else [viri]) if v]
    if not seznam or len(seznam) > NAJVEC_NAENKRAT:
        return {"ok": False, "napaka": "prevec" if seznam else "ni_datoteke", "narejeno": [], "napake": []}
    dom = os.path.expanduser("~")
    narejeno, napake, pari = [], [], []
    for vir in seznam:
        ime = os.path.basename(vir.rstrip(os.sep))
        if not os.path.lexists(vir):
            napake.append({"pot": vir, "napaka": "ni_datoteke"})
            continue
        if vir in ("/", dom) or not ime:
            napake.append({"pot": vir, "napaka": "ni_dovoljeno"})
            continue
        je_mapa = os.path.isdir(vir) and not os.path.islink(vir)
        prava_vir, prava_cilj = os.path.realpath(vir), os.path.realpath(cilj)
        if je_mapa and (prava_cilj == prava_vir or prava_cilj.startswith(prava_vir + os.sep)):
            napake.append({"pot": vir, "napaka": "vase"})
            continue
        if premakni and os.path.realpath(os.path.dirname(vir)) == prava_cilj:
            continue                                    # ze je v tej mapi: nic za narediti
        nova = os.path.join(cilj, _prosto_ime(cilj, ime))
        try:
            if premakni:
                shutil.move(vir, nova)
            elif je_mapa:
                shutil.copytree(vir, nova, symlinks=True)
            else:
                shutil.copy2(vir, nova, follow_symlinks=False)
            narejeno.append(nova)
            pari.append([vir, nova])
        except (OSError, shutil.Error) as e:
            # Napol narejene kopije ne pustimo za sabo (izvirnik je pri kopiranju nedotaknjen).
            if not premakni and os.path.lexists(nova):
                try:
                    shutil.rmtree(nova) if os.path.isdir(nova) and not os.path.islink(nova) else os.remove(nova)
                except OSError:
                    pass
            napake.append({"pot": vir, "napaka": _koda_napake(e) if isinstance(e, OSError) else "napaka"})
    # "pari": od kod kam (za razveljavitev: premik nazaj oziroma kopije v Smeti).
    return {"ok": bool(narejeno) or not napake, "narejeno": narejeno, "napake": napake, "pari": pari}


def razveljavi(zapis) -> dict:
    """Razveljavi dejanje v Datotekah. `zapis` opise, kaj je bilo narejeno (sestavi ga stran iz odgovorov dejanj):
        {"vrsta": "premik", "pari": [[od_kod, kam], ...]}         datoteke gredo nazaj, od koder so prisle
        {"vrsta": "preimenovanje", "pari": [[staro, novo]]}       staro ime
        {"vrsta": "kopija", "pari": [[izvirnik, kopija], ...]}    kopije gredo v Smeti, izvirniki ostanejo
        {"vrsta": "novo", "pari": [["", ustvarjeno]]}             ustvarjeno gre v Smeti
        {"vrsta": "smeti", "idji": [ime v Smeteh, ...]}           datoteke se obnovijo iz Smeti
    Nikoli nicesar ne prepise (zasedeno mesto je napaka) in ne izbrise trajno. Vrne {"ok", "narejeno", "napake"}."""
    if not isinstance(zapis, dict):
        return {"ok": False, "napaka": "ni_zapisa", "narejeno": 0, "napake": []}
    vrsta = str(zapis.get("vrsta") or "")
    pari = [(os.path.abspath(str(p[0])) if p[0] else "", os.path.abspath(str(p[1])))
            for p in (zapis.get("pari") or []) if isinstance(p, (list, tuple)) and len(p) == 2 and p[1]][:NAJVEC_NAENKRAT]
    dom = os.path.expanduser("~")
    narejeno, napake = 0, []
    if vrsta == "smeti":
        for id_ in list(zapis.get("idji") or [])[:NAJVEC_NAENKRAT]:
            r = obnovi_iz_smeti(str(id_))
            if r.get("ok"):
                narejeno += 1
            else:
                napake.append({"pot": str(id_), "napaka": r.get("napaka") or "napaka"})
    elif vrsta in ("premik", "preimenovanje"):
        for nazaj, zdaj in pari:
            if not os.path.lexists(zdaj):
                napake.append({"pot": zdaj, "napaka": "ni_datoteke"})
            elif not nazaj or nazaj in ("/", dom) or zdaj in ("/", dom):
                napake.append({"pot": zdaj, "napaka": "ni_dovoljeno"})
            elif os.path.lexists(nazaj):
                napake.append({"pot": nazaj, "napaka": "obstaja"})
            elif not os.path.isdir(os.path.dirname(nazaj)):
                napake.append({"pot": nazaj, "napaka": "ni_mape"})
            else:
                try:
                    shutil.move(zdaj, nazaj)
                    narejeno += 1
                except (OSError, shutil.Error) as e:
                    napake.append({"pot": zdaj, "napaka": _koda_napake(e) if isinstance(e, OSError) else "napaka"})
    elif vrsta in ("kopija", "novo"):
        for _izvirnik, nastalo in pari:
            r = v_smeti(nastalo)
            if r.get("ok"):
                narejeno += 1
            else:
                napake.append({"pot": nastalo, "napaka": r.get("napaka") or "napaka"})
    else:
        return {"ok": False, "napaka": "ni_zapisa", "narejeno": 0, "napake": []}
    return {"ok": narejeno > 0 and not napake, "narejeno": narejeno, "napake": napake}


# ---------------------------------------------------------------------- vlecenje med programi (text/uri-list)
def poti_iz_naslovov(naslovi) -> list:
    """Poti datotek tega racunalnika iz seznama naslovov, ki ga program poslje ob vlecenju datotek (text/uri-list).
    Kar ni datoteka tega racunalnika (http..., file://drug-racunalnik/...), izpade; najvec NAJVEC_NAENKRAT."""
    import socket
    import urllib.parse
    tukaj = {"", "localhost", socket.gethostname().lower()}
    poti: list = []
    for naslov in list(naslovi or []):
        try:
            # Programi X11 (tudi prek XWayland) in Electron seznam vcasih koncajo z znakom NUL ali presledki.
            deli = urllib.parse.urlsplit(str(naslov).strip().strip("\x00").strip())
        except ValueError:
            continue
        if deli.scheme.lower() != "file" or (deli.netloc or "").lower() not in tukaj:
            continue
        pot = urllib.parse.unquote(deli.path, errors="surrogateescape")
        if not pot.startswith("/") or "\x00" in pot:
            continue
        pot = os.path.normpath(pot)
        if pot not in poti:
            poti.append(pot)
        if len(poti) >= NAJVEC_NAENKRAT:
            break
    return poti


def poti_iz_seznama_naslovov(besedilo) -> list:
    """Poti iz surovega text/uri-list (RFC 2483): vrstice s CRLF ali LF, komentarji #, NUL na koncu (X11, Electron).
    Nekateri programi namesto naslova posljejo kar absolutno pot - sprejmemo jo, ce na tem racunalniku obstaja."""
    if isinstance(besedilo, (bytes, bytearray)):
        besedilo = bytes(besedilo).decode("utf-8", "replace")
    naslovi, poti = [], []
    for vrstica in str(besedilo or "").replace("\x00", "\n").splitlines():
        v = vrstica.strip()
        if not v or v.startswith("#"):
            continue
        if v.startswith("/"):
            if os.path.lexists(v) and v not in poti:
                poti.append(os.path.normpath(v))
            continue
        naslovi.append(v)
    for p in poti_iz_naslovov(naslovi):
        if p not in poti:
            poti.append(p)
    return poti[:NAJVEC_NAENKRAT]


#: Oblike, v katerih vlecenje prinese seznam datotek. GTK iz text/uri-list (in v Flatpaku iz portala dokumentov,
#: application/vnd.portal.filetransfer) sam sestavi Gdk.FileList; surovo beremo samo, ce ga ne zna.
VLECENJE_SUROVO = ("text/uri-list", "text/x-uri-list")


def vrsta_vlecenja(formati) -> str:
    """Kako iz Gdk.Drop dobiti datoteke: "seznam" (Gdk.FileList), "surovo" (text/uri-list beremo sami) ali "" (brez
    datotek). Program iz drugega procesa (Nemo, XWayland, Electron) ponudi samo vrste MIME, brez GType - preverjanje
    contain_gtype(Gdk.FileList) na samem Gdk.Drop je zato zanj vedno False (pregled 18. 10. 2026); GTK zna FileList
    sestaviti iz teh vrst, zato vprasamo po zdruzitvi z vrstami, ki jih zna pretvoriti (union_deserialize_gtypes)."""
    if formati is None:
        return ""
    try:
        from gi.repository import Gdk
        if formati.contain_gtype(Gdk.FileList.__gtype__) or \
                formati.union_deserialize_gtypes().contain_gtype(Gdk.FileList.__gtype__):
            return "seznam"
    except Exception:  # noqa: BLE001 - brez GTK ali stara razlicica: po vrstah MIME
        pass
    try:
        vrste = [str(m).split(";")[0].strip().lower() for m in (formati.get_mime_types() or [])]
    except Exception:  # noqa: BLE001
        vrste = []
    return "surovo" if any(v in VLECENJE_SUROVO for v in vrste) else ""


def preberi_vlecene(spust, ob_poteh, najvec_bajtov: int = 1024 * 1024) -> None:
    """Poti datotek iz Gdk.Drop, asinhrono (podatki vlecenja pridejo prek glavne zanke - branje na njej ne sme cakati).
    ob_poteh(spust, poti) se poklice natanko enkrat, tudi s praznim seznamom. Najprej Gdk.FileList; ce ga GTK ne
    zna sestaviti ali je prazen, surovi text/uri-list."""
    from gi.repository import GLib

    def koncaj(poti) -> None:
        try:
            ob_poteh(spust, list(poti or []))
        except Exception as e:  # noqa: BLE001
            print("[Safeer] vlecenje:", e, flush=True)

    def surovo() -> None:
        try:
            spust.read_async(list(VLECENJE_SUROVO), GLib.PRIORITY_DEFAULT, None, prebran_tok)
        except Exception:  # noqa: BLE001
            koncaj([])

    def prebran_tok(s, izid) -> None:
        try:
            tok, _vrsta = s.read_finish(izid)
        except Exception:  # noqa: BLE001 - vlecenje brez text/uri-list ali preklicano
            koncaj([])
            return
        zbrano = bytearray()

        def kos(t, izid2) -> None:
            try:
                podatki = t.read_bytes_finish(izid2)
            except Exception:  # noqa: BLE001
                podatki = None
            if podatki is not None and podatki.get_size() and len(zbrano) < najvec_bajtov:
                zbrano.extend(podatki.get_data() or b"")
                tok.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, None, kos)
                return
            try:
                tok.close(None)
            except Exception:  # noqa: BLE001
                pass
            koncaj(poti_iz_seznama_naslovov(bytes(zbrano[:najvec_bajtov])))
        tok.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, None, kos)

    def prebran_seznam(s, izid) -> None:
        try:
            seznam = s.read_value_finish(izid)
            naslovi = [f.get_uri() for f in (seznam.get_files() if seznam is not None else [])]
            poti = poti_iz_naslovov(naslovi)
        except Exception:  # noqa: BLE001 - GTK seznama ni znal sestaviti
            poti = []
        if poti:
            koncaj(poti)
        elif vrsta_vlecenja_surovo(spust):
            surovo()
        else:
            koncaj([])

    try:
        from gi.repository import Gdk
        vrsta = vrsta_vlecenja(spust.get_formats())
        if vrsta == "seznam":
            spust.read_value_async(Gdk.FileList.__gtype__, GLib.PRIORITY_DEFAULT, None, prebran_seznam)
        elif vrsta == "surovo":
            surovo()
        else:
            koncaj([])
    except Exception:  # noqa: BLE001
        koncaj([])


def vrsta_vlecenja_surovo(spust) -> bool:
    try:
        vrste = [str(m).split(";")[0].strip().lower() for m in (spust.get_formats().get_mime_types() or [])]
    except Exception:  # noqa: BLE001
        return False
    return any(v in VLECENJE_SUROVO for v in vrste)


def naslovi_iz_poti(poti) -> list:
    """Naslovi file:// obstojecih datotek in map (za vlecenje v drug program); cesar ni, izpade."""
    import urllib.parse
    naslovi: list = []
    for pot in list(poti or [])[:NAJVEC_NAENKRAT]:
        pot = str(pot)
        if os.path.isabs(pot) and os.path.lexists(pot):
            naslovi.append("file://" + urllib.parse.quote(os.path.normpath(pot), safe="/", errors="surrogateescape"))
    return naslovi


# ---------------------------------------------------------------------- Smeti (specifikacija freedesktop, domaca)
def _mapa_smeti() -> str:
    from core import gostitelj
    return os.path.join(gostitelj.podatki_gostitelja(), "Trash")


def _velikost_poti(pot: str, rok: float) -> int:
    """Velikost datoteke ali (do roka) vsebine mape."""
    try:
        if not os.path.isdir(pot) or os.path.islink(pot):
            return os.lstat(pot).st_size
    except OSError:
        return 0
    skupaj, konec = 0, time.monotonic() + rok
    for koren, _mape, datoteke in os.walk(pot):
        for d in datoteke:
            try:
                skupaj += os.lstat(os.path.join(koren, d)).st_size
            except OSError:
                pass
        if time.monotonic() > konec:
            break
    return skupaj


def smeti() -> dict:
    """Vsebina Smeti: najnovejse najprej; `id` je ime v Smeteh (za obnovitev), `izvirna` pot, kjer je bila datoteka."""
    import datetime
    import urllib.parse
    koren = _mapa_smeti()
    datoteke, info = os.path.join(koren, "files"), os.path.join(koren, "info")
    elementi = []
    try:
        imena = os.listdir(datoteke)
    except OSError:
        imena = []
    for ime in imena:
        pot = os.path.join(datoteke, ime)
        izvirna, izbrisano = "", 0.0
        try:
            with open(os.path.join(info, ime + ".trashinfo"), encoding="utf-8", errors="replace") as f:
                for v in f:
                    if v.startswith("Path="):
                        izvirna = urllib.parse.unquote(v[5:].strip())
                    elif v.startswith("DeletionDate="):
                        try:
                            izbrisano = datetime.datetime.strptime(v[13:].strip()[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
                        except ValueError:
                            pass
        except OSError:
            pass
        if izvirna and not os.path.isabs(izvirna):
            izvirna = os.path.join(os.path.dirname(koren), izvirna)
        je_mapa = os.path.isdir(pot) and not os.path.islink(pot)
        prikaz = os.path.basename(izvirna) or ime
        elementi.append({"id": ime, "ime": prikaz, "pot": pot, "izvirna": izvirna, "izbrisano": izbrisano, "mapa": je_mapa,
                         "velikost": 0 if je_mapa else _velikost_poti(pot, 0), "vrsta": vrsta_datoteke(prikaz, je_mapa)})
    elementi.sort(key=lambda e: -e["izbrisano"])
    return {"skupaj": len(elementi), "elementi": elementi[:NAJVEC_V_MAPI]}


def _id_v_smeteh(id_: str) -> Optional[str]:
    ime = str(id_ or "")
    if not ime or "/" in ime or ime in (".", ".."):
        return None
    pot = os.path.join(_mapa_smeti(), "files", ime)
    return pot if os.path.lexists(pot) else None


def obnovi_iz_smeti(id_: str) -> dict:
    """Vrne datoteko tja, kjer je bila; ce je tam medtem nastala druga, dobi ime »ime (2)«."""
    import urllib.parse
    pot = _id_v_smeteh(id_)
    if pot is None:
        return {"ok": False, "napaka": "ni_datoteke"}
    opis = os.path.join(_mapa_smeti(), "info", os.path.basename(pot) + ".trashinfo")
    izvirna = ""
    try:
        with open(opis, encoding="utf-8", errors="replace") as f:
            for v in f:
                if v.startswith("Path="):
                    izvirna = urllib.parse.unquote(v[5:].strip())
    except OSError:
        pass
    if not izvirna:
        return {"ok": False, "napaka": "ni_izvirne_poti"}
    if not os.path.isabs(izvirna):
        izvirna = os.path.join(os.path.dirname(_mapa_smeti()), izvirna)
    mapa = os.path.dirname(izvirna)
    try:
        os.makedirs(mapa, exist_ok=True)
        cilj = os.path.join(mapa, _prosto_ime(mapa, os.path.basename(izvirna)))
        shutil.move(pot, cilj)
    except OSError as e:
        return {"ok": False, "napaka": _koda_napake(e)}
    try:
        os.remove(opis)
    except OSError:
        pass
    return {"ok": True, "pot": cilj}


def izprazni_smeti() -> dict:
    """TRAJNO izbrise vsebino Smeti. Klicatelj (Safeer OS) mora prej dobiti potrditev v sistemskem oknu."""
    koren = _mapa_smeti()
    izbrisano = 0
    for podmapa in ("files", "info"):
        mapa = os.path.join(koren, podmapa)
        try:
            imena = os.listdir(mapa)
        except OSError:
            continue
        for ime in imena:
            pot = os.path.join(mapa, ime)
            try:
                if os.path.isdir(pot) and not os.path.islink(pot):
                    shutil.rmtree(pot)
                else:
                    os.remove(pot)
                izbrisano += podmapa == "files"
            except OSError:
                pass
    return {"ok": True, "izbrisano": izbrisano}


# ---------------------------------------------------------------------- nosilci (USB, drugi diski, omrezna mesta)
_SISTEMSKE_TOCKE = ("/", "/boot", "/boot/efi", "/home", "/var", "/usr", "/tmp", "[SWAP]")


def _nosilci_lsblk(izpis: str, uporabnik: str) -> List[dict]:
    """Nosilci iz izpisa `lsblk -J -b -o NAME,PATH,LABEL,SIZE,TYPE,RM,HOTPLUG,MOUNTPOINT,FSTYPE` (cista funkcija)."""
    import json as _json
    try:
        drevo = _json.loads(izpis).get("blockdevices") or []
    except ValueError:
        return []
    izid = []

    def obisci(n: dict, odstranljiv: bool) -> None:
        odstranljiv = odstranljiv or bool(n.get("rm")) or bool(n.get("hotplug"))
        tocka = n.get("mountpoint") or ""
        if tocka and tocka not in _SISTEMSKE_TOCKE and not tocka.startswith(("/snap/", "/boot/", "/var/", "/sys", "/proc", "/dev")):
            mediji = tocka.startswith(("/media/" + uporabnik + "/", "/run/media/" + uporabnik + "/", "/mnt/", "/media/"))
            if mediji or odstranljiv:
                izid.append({"ime": str(n.get("label") or os.path.basename(tocka) or n.get("name") or ""), "pot": tocka,
                             "naprava": str(n.get("path") or ""), "odstranljiv": odstranljiv,
                             "velikost": int(n.get("size") or 0)})
        for o in n.get("children") or []:
            obisci(o, odstranljiv)

    for n in drevo:
        obisci(n, False)
    return izid


def nosilci() -> List[dict]:
    """Priklopljeni nosilci poleg sistemskega diska (USB kljuci, zunanji in drugi diski) ter omrezna mesta (gvfs)."""
    import getpass
    izid: List[dict] = []
    if shutil.which("lsblk"):
        try:
            r = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,LABEL,SIZE,TYPE,RM,HOTPLUG,MOUNTPOINT,FSTYPE"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                izid = _nosilci_lsblk(r.stdout, getpass.getuser())
        except (OSError, subprocess.SubprocessError):
            pass
    for n in izid:
        try:
            st = os.statvfs(n["pot"])
            n["prosto"] = st.f_bavail * st.f_frsize
        except OSError:
            n["prosto"] = 0
    gvfs = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(), "gvfs")
    try:
        for ime in sorted(os.listdir(gvfs)):
            izid.append({"ime": ime.split(",")[0].replace(":host=", " ").replace("smb-share:server=", ""), "pot": os.path.join(gvfs, ime),
                         "naprava": "", "odstranljiv": False, "velikost": 0, "prosto": 0, "omrezje": True})
    except OSError:
        pass
    return izid


def izvrzi(pot: str) -> dict:
    """Varno odstrani nosilec: odklopi datotecni sistem in (USB) izklopi napravo. Samo nosilci s seznama `nosilci()`."""
    cilj = next((n for n in nosilci() if n["pot"] == str(pot or "") and n.get("naprava")), None)
    # udisksctl samo iz sistemskih map, ne po PATH: odklop sistemskega nosilca polkit zavaruje z geslom (root_ukaz).
    from core import root_ukaz
    udisksctl = root_ukaz.sistemski_program("udisksctl")
    if cilj is None or not udisksctl:
        return {"ok": False, "napaka": "ni_nosilca"}
    try:
        r = subprocess.run([udisksctl, "unmount", "-b", cilj["naprava"]], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"ok": False, "napaka": "zaseden" if "busy" in (r.stderr + r.stdout).lower() else "napaka"}
        if cilj.get("odstranljiv"):
            subprocess.run([udisksctl, "power-off", "-b", cilj["naprava"]], capture_output=True, text=True, timeout=30)
        return {"ok": True}
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "napaka": "napaka"}


# ---------------------------------------------------------------------- lastnosti
def lastnosti(pot: str) -> dict:
    import pwd
    import stat as _stat
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    try:
        st = os.lstat(pot)
    except OSError:
        return {"ok": False, "napaka": "ni_datoteke"}
    je_povezava = _stat.S_ISLNK(st.st_mode)
    je_mapa = os.path.isdir(pot) and not je_povezava
    try:
        lastnik = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        lastnik = str(st.st_uid)
    izid = {"ok": True, "ime": os.path.basename(pot) or pot, "pot": pot, "mapa": je_mapa,
            "vrsta": vrsta_datoteke(os.path.basename(pot), je_mapa), "mime": "inode/directory" if je_mapa else (mimetypes.guess_type(pot)[0] or ""),
            "velikost": _velikost_poti(pot, 1.0), "spremenjeno": st.st_mtime, "pravice": _stat.filemode(st.st_mode),
            "lastnik": lastnik, "pisljivo": os.access(pot, os.W_OK)}
    if je_povezava:
        try:
            izid["povezava"] = os.readlink(pot)
        except OSError:
            izid["povezava"] = ""
    if je_mapa:
        try:
            izid["vsebuje"] = len(os.listdir(pot))
        except OSError:
            izid["vsebuje"] = 0
    return izid


# ---------------------------------------------------------------------- predogled (preslednica v Datotekah)
#: Besedilo: najvec toliko z zacetka datoteke (vecja se nikoli ne prebere vsa) - kot Quick Look.
MEJA_BESEDILA = 200 * 1024
#: Slika vecja od tega se v predogledu ne nalozi (QML bi jo dekodiral v pomnilnik); pokazemo podatke in »Odpri«.
MEJA_SLIKE = 80 * 1024 * 1024
#: Zapisi slik, za katere Qt v Safeerju (PySide6 Essentials: imageformats brez HEIF/AVIF/JXL/RAW) nima dekodirnika.
#: QML Image bi jih poskusil nalozit in koncal z Image.Error (»Predogleda ni mogoce pokazati«), RAW (.dng ...) pa
#: mimetypes sploh ne pozna kot sliko. Predogled zato pove razlog in ponudi »Odpri« (zunanji ogled slik).
BREZ_DEKODIRNIKA = (".heic", ".heif", ".hif", ".avif", ".jxl", ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw",
                    ".srf", ".sr2", ".raf", ".orf", ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".mrw",
                    ".kdc", ".dcr", ".mos", ".raw", ".rwl")
#: Koncnice, ki so besedilo, ceprav jih mimetypes ne pozna kot text/* (koda, nastavitve, dnevniki).
BESEDILNE = (".txt", ".md", ".py", ".js", ".mjs", ".ts", ".qml", ".json", ".csv", ".tsv", ".xml", ".html", ".htm", ".css",
             ".sh", ".bash", ".zsh", ".c", ".h", ".cpp", ".hpp", ".cc", ".rs", ".go", ".java", ".kt", ".rb", ".php", ".pl",
             ".lua", ".sql", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".log", ".desktop", ".srt", ".vtt", ".tex",
             ".rst", ".svg", ".diff", ".patch", ".gitignore", ".env")


def _besedilo_z_zacetka(pot: str, meja: int = MEJA_BESEDILA) -> Optional[dict]:
    """Prvih `meja` bajtov kot besedilo ali None, ce je datoteka binarna (nicelni bajt ali ne-UTF-8 v vzorcu).
    O_NONBLOCK in fstat: ce je bila datoteka med preverjanjem in odpiranjem zamenjana s cevjo ali napravo, branje ne
    obvisi (nit mostu bi cakala za vedno) - beremo samo navadno datoteko."""
    import stat as _stat
    with open(pot, "rb", opener=lambda p, z: os.open(p, z | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0))) as f:
        if not _stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError("ni_navadna")
        podatki = f.read(meja + 1)
    odrezano = len(podatki) > meja
    podatki = podatki[:meja]
    vzorec = podatki[:8192]
    if b"\0" in vzorec:
        return None
    try:
        vzorec.decode("utf-8")
    except UnicodeDecodeError as e:
        # Na koncu vzorca je lahko prerezan vecbajtni znak; drugje pomeni, da to ni UTF-8 besedilo.
        if e.start < len(vzorec) - 4:
            try:
                vzorec.decode("latin-1")
                if sum(1 for b in vzorec if b < 9 or 13 < b < 32) > len(vzorec) // 100:
                    return None
                return {"besedilo": podatki.decode("latin-1"), "odrezano": odrezano, "kodiranje": "latin-1", "prebrano": len(podatki)}
            except UnicodeDecodeError:
                return None
    return {"besedilo": podatki.decode("utf-8", errors="replace"), "odrezano": odrezano, "kodiranje": "utf-8", "prebrano": len(podatki)}


def _mapa_predogledov() -> str:
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os", "predogled")


#: Najvec slik prvih strani v predpomnilniku (starejse gredo; ena je nekaj sto KB).
NAJVEC_PREDOGLEDOV = 100


def _pospravi_predoglede(mapa: str, najvec: int = NAJVEC_PREDOGLEDOV) -> None:
    try:
        slike = sorted((e for e in os.scandir(mapa) if e.name.endswith(".png") and e.is_file(follow_symlinks=False)),
                       key=lambda e: e.stat(follow_symlinks=False).st_mtime, reverse=True)
    except OSError:
        return
    for e in slike[najvec:]:
        try:
            os.remove(e.path)
        except OSError:
            pass


#: Casovna meja za sliko prve strani: pokvarjen ali zlonameren PDF ne sme zadrzati predogleda ali slicice priponke.
CAS_PRVE_STRANI_S = 15


def slika_prve_strani(pot: str, cilj: str, velikost: int = 1200, najdi=shutil.which,
                      cas: float = CAS_PRVE_STRANI_S) -> bool:
    """Prva stran PDF kot PNG v `cilj` (daljsa stranica `velikost` px) z orodjem pdftoppm (poppler-utils; v Flatpaku
    /app/bin/pdftoppm). Vrne True, ce je slika narejena. PDF-ja ne razclenjujemo v tem procesu (Poppler GI): pokvarjen
    ali zlonameren PDF bi podrl Safeer OS, Control in Splet hkrati (en proces) - pdftoppm tece loceno, s casovno mejo,
    in v `cilj` pride samo cela slika (prekinjena po casovni meji bi tam ostala pokvarjena za vedno)."""
    import threading
    orodje = najdi("pdftoppm")
    if not orodje:
        return False
    zacasna = "%s.%d.%d" % (cilj[:-4] if cilj.endswith(".png") else cilj, os.getpid(), threading.get_ident())
    try:
        r = subprocess.run([orodje, "-f", "1", "-l", "1", "-singlefile", "-png", "-scale-to", str(int(velikost)),
                            "--", pot, zacasna],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=cas,
                           check=False)
        if r.returncode == 0 and os.path.isfile(zacasna + ".png"):
            os.chmod(zacasna + ".png", 0o600)          # slike strani zasebnih dokumentov vidi samo uporabnik
            os.replace(zacasna + ".png", cilj)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if os.path.exists(zacasna + ".png"):
            try:
                os.remove(zacasna + ".png")
            except OSError:
                pass
    return False


def _prva_stran_pdf(pot: str, st: os.stat_result, najdi=shutil.which) -> str:
    """Prva stran PDF kot PNG v predpomnilniku (pdftoppm iz poppler-utils); prazno brez orodja.
    Predpomnilnik se obnovi, ko se PDF spremeni."""
    import hashlib
    kljuc = hashlib.sha1(("%s|%d|%d" % (pot, st.st_size, int(st.st_mtime))).encode("utf-8", "surrogateescape")).hexdigest()[:24]
    cilj = os.path.join(_mapa_predogledov(), kljuc + ".png")
    if os.path.isfile(cilj):
        return cilj
    # 0700: slike strani zasebnih dokumentov vidi samo uporabnik.
    os.makedirs(os.path.dirname(cilj), mode=0o700, exist_ok=True)
    # Brez pdftoppm ni slike strani (»Odpri« ostane).
    if slika_prve_strani(pot, cilj, 1200, najdi):
        _pospravi_predoglede(os.path.dirname(cilj))
        return cilj
    return ""


def predogled(pot: str, najdi=shutil.which) -> dict:
    """Podatki za predogled datoteke (preslednica ali »Predogled« v Datotekah). Samo navadne datoteke (ne naprave,
    cevi, vticnice - branje bi lahko obviselo); besedilo samo do MEJA_BESEDILA, binarno se ne pokaze kot besedilo.
    Vrne {"ok", "nacin": slika|besedilo|pdf|medij|podatki, ime, pot, velikost, spremenjeno, mime, ...}."""
    import stat as _stat
    pot = os.path.abspath(os.path.expanduser(str(pot or "")))
    try:
        st = os.stat(pot)
    except OSError:
        return {"ok": False, "napaka": "ni_datoteke"}
    if _stat.S_ISDIR(st.st_mode):
        return {"ok": False, "napaka": "mapa"}
    if not _stat.S_ISREG(st.st_mode):
        return {"ok": False, "napaka": "ni_navadna"}
    ime = os.path.basename(pot)
    vrsta = vrsta_datoteke(ime)
    mime = mimetypes.guess_type(ime)[0] or ""
    izid = {"ok": True, "nacin": "podatki", "ime": ime, "pot": pot, "vrsta": vrsta, "mime": mime,
            "velikost": st.st_size, "spremenjeno": st.st_mtime}
    konc = os.path.splitext(ime)[1].lower() or ime.lower()
    if konc in BREZ_DEKODIRNIKA:
        izid["brezDekodirnika"] = True
        return izid
    if vrsta == "slika" and konc != ".svg":
        if st.st_size <= MEJA_SLIKE:
            izid["nacin"] = "slika"
        else:
            izid["prevelika"] = True
        return izid
    if vrsta in ("zvok", "video"):
        izid["nacin"] = "medij"
        return izid
    if konc == ".pdf":
        stran = _prva_stran_pdf(pot, st, najdi)
        if stran:
            izid.update(nacin="pdf", slika=stran)
        else:
            izid["brezOrodja"] = True
        return izid
    if mime.startswith("text/") or konc in BESEDILNE or (not mime and st.st_size <= 4 * 1024 * 1024):
        try:
            b = _besedilo_z_zacetka(pot)
        except OSError as e:
            return dict(izid, ok=False, napaka="ni_navadna" if str(e) == "ni_navadna" else "ni_dovoljenja")
        if b is not None:
            izid.update(nacin="besedilo", **b)
        else:
            izid["binarno"] = True
    return izid


def v_smeti_vec(poti) -> dict:
    """Vec datotek in map v Smeti (izbira v Datotekah): {"ok", "idji", "narejeno": [poti], "napake"}. Idji gredo v en
    zapis za Razveljavi, da Ctrl+Z vrne VSE, kar je slo v Smeti z enim dejanjem."""
    seznam = [str(p) for p in (poti if isinstance(poti, (list, tuple)) else [poti]) if p]
    if not seznam or len(seznam) > NAJVEC_NAENKRAT:
        return {"ok": False, "napaka": "prevec" if seznam else "ni_datoteke", "najvec": NAJVEC_NAENKRAT, "idji": [],
                "narejeno": [], "napake": []}
    idji, narejeno, napake = [], [], []
    for pot in dict.fromkeys(seznam):
        r = v_smeti(pot)
        if r.get("ok"):
            narejeno.append(pot)
            if r.get("id"):
                idji.append(r["id"])
        else:
            napake.append({"pot": pot, "napaka": r.get("napaka") or "napaka"})
    return {"ok": bool(narejeno) and not napake, "idji": idji, "narejeno": narejeno, "napake": napake}


# ---------------------------------------------------------------------- slicice
SLICICA_VELIKOST = 256
_SLIKE = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff")


def _mapa_slicic() -> str:
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os", "slicice")


def slicica(pot: str) -> str:
    """Pot do slicice (PNG/JPEG) za sliko ali video; prazno, ce je ni mogoce dobiti. Najprej skupni predpomnilnik
    namizja (~/.cache/thumbnails, ki ga polni Nemo - tam so tudi slicice videov), sicer sliko pomanjsamo sami."""
    import hashlib
    import urllib.parse
    pot = os.path.abspath(str(pot or ""))
    try:
        st = os.stat(pot)
    except OSError:
        return ""
    if not os.path.isfile(pot):
        return ""
    uri = "file://" + urllib.parse.quote(pot)
    md5 = hashlib.md5(uri.encode("utf-8"), usedforsecurity=False).hexdigest()
    skupni = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "thumbnails")
    for podmapa in ("large", "normal", "x-large"):
        kandidat = os.path.join(skupni, podmapa, md5 + ".png")
        try:
            if os.stat(kandidat).st_mtime >= st.st_mtime - 1:
                return kandidat
        except OSError:
            pass
    if not pot.lower().endswith(_SLIKE) or st.st_size > 60 * 1024 * 1024:
        return ""
    cilj = os.path.join(_mapa_slicic(), md5 + ".jpg")
    try:
        if os.stat(cilj).st_mtime >= st.st_mtime:
            return cilj
    except OSError:
        pass
    try:
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = 120_000_000
        os.makedirs(os.path.dirname(cilj), exist_ok=True)
        with Image.open(pot) as s:
            s = ImageOps.exif_transpose(s)
            s.thumbnail((SLICICA_VELIKOST, SLICICA_VELIKOST))
            if s.mode not in ("RGB", "L"):
                ozadje = Image.new("RGB", s.size, (16, 26, 43))
                ozadje.paste(s.convert("RGBA"), mask=s.convert("RGBA").split()[3])
                s = ozadje
            s.save(cilj + ".tmp", "JPEG", quality=82)
        os.replace(cilj + ".tmp", cilj)
        return cilj
    except Exception:  # noqa: BLE001 - poskodovana slika ali brez Pillow: brez slicice
        try:
            os.remove(cilj + ".tmp")
        except OSError:
            pass
        return ""


def slicice(poti, rok: float = 4.0) -> dict:
    """Slicice za vec datotek naenkrat (do roka): {pot: pot_slicice}; brez vnosa = slicice ni."""
    izid, konec = {}, time.monotonic() + rok
    for pot in list(poti or [])[:120]:
        if time.monotonic() > konec:
            break
        s = slicica(str(pot))
        if s:
            izid[str(pot)] = s
    return izid


# ---------------------------------------------------------------------- spremembe v prikazanem pogledu
class NadzorMap:
    """Pove, ko se v pogledu Datotek, ki ga stran kaze, kaj spremeni - tudi ce to naredi drug program (prenos iz
    brskalnika, Nemo, datoteka z druge naprave): datoteka se pojavi, izgine, preimenuje ali raste. Stran pove, kaj
    kaze ([spremljaj]), ob obvestilu pa seznam prebere znova (4. 10. 2026: prej se je mapa prebrala samo ob odprtju).

    Pogled je pot mape, [NEDAVNO] ali [SMETI]. Nova, izbrisana ali preimenovana datoteka pride do strani v manj kot
    sekundi; datoteka, ki raste (prenos), osvezi velikost najvec na nekaj sekund; razpakiranje arhiva (tisoce
    sprememb) najvec enkrat na sekundo. Zraven javi priklop in odklop nosilcev (USB kljuc, disk).

    Tece v glavni zanki GLib (klici iz njene niti); brez GLib ne naredi nicesar."""

    NEDAVNO, SMETI = "@nedavno", "@smeti"
    _NOSILCI = "@nosilci"
    HITRO_MS = 400          # nova, izbrisana ali preimenovana datoteka
    POCASI_MS = 2500        # datoteka se spreminja (prenos raste)
    NAJMANJ_MED_MS = 1000   # med dvema obvestiloma za isti pogled
    NOSILCI_MS = 600        # priklop nosilca sprozi vec signalov zapored

    def __init__(self, ob_spremembi, ob_nosilcih=None) -> None:
        self._ob_spremembi = ob_spremembi       # ob_spremembi(pogled)
        self._ob_nosilcih = ob_nosilcih         # ob_nosilcih()
        self._pogledi: dict = {}                # kljuc strani -> pogled
        self._nadzori: dict = {}                # pogled -> [nadzor Gio, ...]
        self._casovniki: dict = {}              # pogled -> (vir GLib, rok v ms)
        self._zadnje: dict = {}                 # pogled -> cas zadnjega obvestila v ms
        self._nosilci = None
        self._nosilci_povezave: list = []

    @staticmethod
    def veljaven(pogled) -> str:
        """Pogled, ki ga smemo spremljati: NEDAVNO, SMETI ali absolutna pot obstojece mape; sicer prazno."""
        pogled = str(pogled or "")
        if pogled in (NadzorMap.NEDAVNO, NadzorMap.SMETI):
            return pogled
        if pogled.startswith("/") and "\0" not in pogled and os.path.isdir(pogled):
            return os.path.abspath(pogled)
        return ""

    @staticmethod
    def hitrost(vrsta: str, ime: str, drugo: str = "") -> int:
        """Kako hitro javiti dogodek nadzora: HITRO_MS, POCASI_MS ali 0 (seznama ne zadeva). `vrsta` je ime dogodka
        Gio (created, deleted, renamed, moved-in, moved-out, changed, changes-done-hint, attribute-changed ...);
        `drugo` je novo ime pri preimenovanju."""
        if not any(x and not x.startswith(".") for x in (ime, drugo)):
            return 0                    # skritih datotek seznam ne kaze (zacasne datoteke programov)
        if vrsta in ("created", "deleted", "renamed", "moved-in", "moved-out", "moved"):
            return NadzorMap.HITRO_MS
        if vrsta in ("changed", "changes-done-hint"):
            return NadzorMap.POCASI_MS
        return 0

    @staticmethod
    def _mape_smeti() -> list:
        """Mapa z datotekami v Smeteh in mapi nad njo: Smeti na svezem racunalniku se ni, nastane ob prvem brisanju.
        [(mapa, ime, ki nas v njej zanima ali "" = vse)]."""
        koren = _mapa_smeti()
        return [(os.path.join(koren, "files"), ""), (koren, "files"), (os.path.dirname(koren), os.path.basename(koren))]

    def spremljaj(self, kljuc, pogled) -> bool:
        """Stran [kljuc] zdaj kaze [pogled] (prazno = nic, kar bi spremljali). Vrne, ali pogled spremljamo."""
        pogled = self.veljaven(pogled)
        if pogled:
            self._pogledi[kljuc] = pogled
        else:
            self._pogledi.pop(kljuc, None)
        self._uskladi()
        return bool(pogled) and (pogled == self.NEDAVNO or bool(self._nadzori.get(pogled)))

    def obdrzi(self, kljuci) -> None:
        """Strani, ki jih ni vec (zaprto okno), ne spremljamo naprej."""
        for kljuc in [k for k in self._pogledi if k not in kljuci]:
            self._pogledi.pop(kljuc, None)

    def pogledi(self) -> list:
        return sorted(set(self._pogledi.values()))

    def zunanja(self, pogled: str) -> None:
        """Spremembo pogleda je javil nekdo drug (seznam nedavnih vodi GTK)."""
        if pogled in self._pogledi.values():
            self._nacrtuj(pogled, self.HITRO_MS)

    def _postavi(self, pogled: str) -> list:
        from gi.repository import Gio
        mape = self._mape_smeti() if pogled == self.SMETI else [(pogled, "")]
        nadzori = []
        for mapa, samo_ime in mape:
            if not os.path.isdir(mapa):
                continue
            try:
                nadzor = Gio.File.new_for_path(mapa).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
                nadzor.connect("changed", self._sprememba, pogled, samo_ime)
                nadzori.append(nadzor)
            except Exception:  # noqa: BLE001
                continue
        return nadzori

    @staticmethod
    def _ustavi(nadzori) -> None:
        for nadzor in nadzori or []:
            try:
                nadzor.cancel()
            except Exception:  # noqa: BLE001
                pass

    def _uskladi(self) -> None:
        try:
            from gi.repository import Gio  # noqa: F401
        except Exception:  # noqa: BLE001
            return
        zeleni = set(self._pogledi.values())
        for pogled in [p for p in self._nadzori if p not in zeleni]:
            self._ustavi(self._nadzori.pop(pogled))
            self._preklici(pogled)
        for pogled in zeleni:
            if pogled != self.NEDAVNO and pogled not in self._nadzori:
                self._nadzori[pogled] = self._postavi(pogled)
        self._zacni_nosilce()

    def _sprememba(self, _nadzor, datoteka, druga, vrsta, pogled, samo_ime) -> None:
        try:
            ime = datoteka.get_basename() or ""
            drugo = (druga.get_basename() or "") if druga is not None else ""
            vrsta = vrsta.value_nick
        except Exception:  # noqa: BLE001
            return
        if samo_ime:
            # Mapa nad Smetmi: zanima nas samo nastanek mape Smeti.
            if samo_ime in (ime, drugo) and vrsta in ("created", "moved-in", "renamed"):
                self._nacrtuj(pogled, self.HITRO_MS)
            return
        zamik = self.hitrost(vrsta, ime, drugo)
        if zamik:
            self._nacrtuj(pogled, zamik)

    def _nacrtuj(self, pogled: str, zamik_ms: int) -> None:
        from gi.repository import GLib
        zdaj = GLib.get_monotonic_time() // 1000
        rok = max(zdaj + zamik_ms, self._zadnje.get(pogled, 0) + self.NAJMANJ_MED_MS)
        obstojeci = self._casovniki.get(pogled)
        if obstojeci:
            if obstojeci[1] <= rok:
                return                  # ze nacrtovano prej ali ob istem casu
            GLib.source_remove(obstojeci[0])
        self._casovniki[pogled] = (GLib.timeout_add(max(1, rok - zdaj), self._poslji, pogled), rok)

    def _preklici(self, pogled: str) -> None:
        obstojeci = self._casovniki.pop(pogled, None)
        if obstojeci:
            try:
                from gi.repository import GLib
                GLib.source_remove(obstojeci[0])
            except Exception:  # noqa: BLE001
                pass

    def _poslji(self, pogled: str) -> bool:
        self._casovniki.pop(pogled, None)
        try:
            from gi.repository import GLib
            self._zadnje[pogled] = GLib.get_monotonic_time() // 1000
        except Exception:  # noqa: BLE001
            pass
        try:
            if pogled == self._NOSILCI:
                if self._ob_nosilcih is not None:
                    self._ob_nosilcih()
            elif pogled in self._pogledi.values():
                if pogled == self.SMETI:
                    # Mapa Smeti je morda pravkar nastala: nadzor postavimo znova (zdaj neposredno nanjo).
                    self._ustavi(self._nadzori.get(pogled))
                    self._nadzori[pogled] = self._postavi(pogled)
                self._ob_spremembi(pogled)
        except Exception:  # noqa: BLE001
            pass
        return False

    def _zacni_nosilce(self) -> None:
        if self._nosilci is not None or self._ob_nosilcih is None:
            return
        try:
            from gi.repository import Gio
            self._nosilci = Gio.VolumeMonitor.get()
            for signal in ("mount-added", "mount-removed", "volume-added", "volume-removed"):
                self._nosilci_povezave.append(self._nosilci.connect(signal, lambda *_a: self._nacrtuj(self._NOSILCI, self.NOSILCI_MS)))
        except Exception:  # noqa: BLE001
            self._nosilci = False

    def koncaj(self) -> None:
        for pogled in list(self._nadzori):
            self._ustavi(self._nadzori.pop(pogled))
        for pogled in list(self._casovniki):
            self._preklici(pogled)
        self._pogledi = {}
        if self._nosilci:
            for povezava in self._nosilci_povezave:
                try:
                    self._nosilci.disconnect(povezava)
                except Exception:  # noqa: BLE001
                    pass
        self._nosilci, self._nosilci_povezave = None, []
