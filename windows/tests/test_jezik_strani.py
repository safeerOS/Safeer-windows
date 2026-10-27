"""Ves vmesnik Safeer OS / Player v jeziku vmesnika - brez mesanja sl/en (naloga 40, 27. 10. 2026).

Lastnik: »Medijski center je na Windows mesan v slovenscini in anglescini«. assets/os/index.html je imel trdo slovenska
besedila brez data-t (prevedi() jih ni videl), os.js pa slovenske literale (zvrsti, »Viri in jeziki: ...«, epizode).
Kot Linux tests/test_os_linux.py Stran.test_elementi_in_prevodi.
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parents[2]
OS = KOREN / "assets" / "os"
JEZIKI = ("sl", "en", "de", "es", "fr", "it")

#: Besedila v index.html, ki se ne prevajajo: lastna imena, oznake izdelkov, tehnicni nizi.
LASTNA_IMENA = {
    "Safeer OS", "Safeer Link", "SAFEER BROWSER", "CC", "Jellyfin", "Emby", "Navidrome", "Plex", "TVHeadend", "DLNA / UPnP",
    "Funkwhale", "AzuraCast", "SAFEER MEDIA · SAFEER LINK", "SAFEER MEDIA · DEBRID", "SAFEER MEDIA · MAGNET", "Chatwoot",
    "Matrix", "Telegram Bot",
}
#: Placeholderji, ki so primer naslova ali protokol (enaki v vseh jezikih).
TEHNICNI_PH = {"https://...", "magnet:?xt=urn:btih:…", "IMAP", "SMTP", "https://chatwoot.example", "https://matrix.org"}
#: Literali v os.js, ki niso besedilo za uporabnika: selektorji, razredi CSS, kljuci podatkov, lastno ime.
DOVOLJENI_LITERALI = {
    "#meni button.izbran", "#meni button", "pozabi poslji-na", "#vsebinaMape .vrstica", "@iskanje", "magnetVrsta_drugo",
    "magnetVrsta_slika", "mediaNapaka_ni_toka", "naročnina", "brezplačno", "RTV 365",
    "brez mosta",       # razlog Promise.reject, ki ga primerja obvescanje (prikaze t("brezMostu"))
}
BREZ = {"script", "style", "svg", "path", "code", "kbd", "template", "title"}
PRAZNI = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sklad, self.besedila, self.atributi, self.kljuci = [], [], [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k in ("data-t", "data-ph", "data-naslov", "data-aria"):
            if a.get(k):
                self.kljuci.add(a[k])
        for atr, kljuc in (("placeholder", "data-ph"), ("title", "data-naslov"), ("aria-label", "data-aria")):
            if a.get(atr) and not a.get(kljuc) and not (atr == "placeholder" and a[atr] in TEHNICNI_PH):
                self.atributi.append((self.getpos()[0], atr, a[atr]))
        preskoci = (self.sklad[-1][1] if self.sklad else False) or tag in BREZ or "data-t" in a
        if tag not in PRAZNI:
            self.sklad.append((tag, preskoci))

    def handle_endtag(self, tag):
        for i in range(len(self.sklad) - 1, -1, -1):
            if self.sklad[i][0] == tag:
                del self.sklad[i:]
                break

    def handle_data(self, data):
        if self.sklad and self.sklad[-1][1]:
            return
        s = " ".join(data.split())
        if re.search(r"[A-Za-zČŠŽčšž]", s) and s not in LASTNA_IMENA:
            self.besedila.append((self.getpos()[0], s))


def _html() -> _Html:
    h = _Html()
    h.feed((OS / "index.html").read_text(encoding="utf-8"))
    return h


def _blok(vir: str, ime: str) -> str:
    """`var IME = {...};` iz os.js (nizi upostevani)."""
    m = re.search(r"var %s = \{" % ime, vir)
    i = j = m.end() - 1
    globina, niz = 0, None
    while j < len(vir):
        c = vir[j]
        if niz:
            if c == "\\":
                j += 2
                continue
            if c == niz:
                niz = None
        elif c in "\"'":
            niz = c
        elif c == "{":
            globina += 1
        elif c == "}":
            globina -= 1
            if globina == 0:
                break
        j += 1
    return "var %s = %s;" % (ime, vir[i:j + 1])


@pytest.fixture(scope="module")
def slovar():
    """BESEDILA_OS, kot je na Windows po zagonu strani (besedila.js + BESEDILA_MEDIA + BESEDILA_WINDOWS)."""
    qtqml = pytest.importorskip("PySide6.QtQml")
    # QApplication (ne QCoreApplication): kasnejsi preizkusi v istem procesu ustvarjajo okna - s QCoreApplication
    # se je pytest sesul (koda 127 v test_link_deli_z.py).
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    vir = (OS / "os.js").read_text(encoding="utf-8")
    koda = (OS / "besedila.js").read_text(encoding="utf-8") + "\n" + "\n".join(
        _blok(vir, ime) for ime in ("BESEDILA_WINDOWS", "BESEDILA_VRATA", "BESEDILA_MEDIA")) + """
Object.keys(BESEDILA_VRATA).forEach(function (k) { Object.assign(BESEDILA_WINDOWS[k], BESEDILA_VRATA[k]); });
Object.keys(BESEDILA_MEDIA).forEach(function (k) { if (BESEDILA_OS[k]) Object.assign(BESEDILA_OS[k], BESEDILA_MEDIA[k]); });
Object.keys(BESEDILA_WINDOWS).forEach(function (k) { if (BESEDILA_OS[k]) Object.assign(BESEDILA_OS[k], BESEDILA_WINDOWS[k]); });
JSON.stringify(BESEDILA_OS)"""
    motor = qtqml.QJSEngine()
    r = motor.evaluate(koda)
    assert not r.isError(), r.toString()
    return json.loads(r.toString())


def test_vsa_besedila_strani_imajo_kljuc():
    h = _html()
    assert h.besedila == [], "besedila brez data-t (vrstica, besedilo): %s" % h.besedila


def test_placeholder_title_aria_imajo_kljuc():
    h = _html()
    assert h.atributi == [], "atributi brez data-ph / data-naslov / data-aria: %s" % h.atributi


def test_vsak_kljuc_strani_v_vseh_jezikih(slovar):
    manjka = sorted((j, k) for k in _html().kljuci for j in JEZIKI
                    if not isinstance(slovar.get(j, {}).get(k), str) or not slovar[j][k].strip())
    assert manjka == [], manjka


def test_kljuci_os_js_v_vseh_jezikih(slovar):
    vir = (OS / "os.js").read_text(encoding="utf-8")
    # t("kljuc") in t("kljuc_" + ...) - pri drugem je kljuc sestavljen, zato le celi kljuci
    kljuci = set(re.findall(r'\bt\("([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)"\s*[,)]', vir))
    manjka = sorted((j, k) for k in kljuci for j in JEZIKI if not isinstance(slovar.get(j, {}).get(k), str))
    assert manjka == [], manjka


def _literali(vir: str):
    """(vrstica, niz) za nize '...' in "..." zunaj komentarjev in blokov BESEDILA_*."""
    bloki = []
    for m in re.finditer(r"var BESEDILA_[A-Z_]+ = \{", vir):
        b = _blok(vir, m.group(0)[4:-4])
        bloki.append((m.start(), m.start() + len(b)))
    izid, i, n, vrstica = [], 0, len(vir), 1
    while i < n:
        blok = next((b for b in bloki if b[0] <= i < b[1]), None)
        if blok:
            vrstica += vir.count("\n", i, blok[1])
            i = blok[1]
            continue
        c = vir[i]
        if c == "\n":
            vrstica += 1
        elif vir.startswith("//", i):
            k = vir.find("\n", i)
            i = n if k < 0 else k
            continue
        elif vir.startswith("/*", i):
            k = vir.find("*/", i) + 2
            vrstica += vir.count("\n", i, k)
            i = k
            continue
        elif c in "\"'`":
            j = i + 1
            while j < n and vir[j] != c:
                j += 2 if vir[j] == "\\" else 1
            s = vir[i + 1:j]
            izid.append((vrstica, s))
            vrstica += s.count("\n")
            i = j + 1
            continue
        elif c == "/" and (vir[max(0, i - 20):i].rstrip()[-1:] or "(") in "=(,:!&|?;{}[":
            j = i + 1
            while j < n and vir[j] not in "/\n":
                j += 2 if vir[j] == "\\" else 1
            i = j + 1
            continue
        i += 1
    return izid


def test_os_js_brez_slovenskih_literalov(slovar):
    vir = (OS / "os.js").read_text(encoding="utf-8")

    def besede(jez):
        r = set()
        for v in slovar[jez].values():
            if isinstance(v, str):
                r.update(w.lower() for w in re.findall(r"[A-Za-zČŠŽčšž]{3,}", v))
        return r
    tuje = set().union(*(besede(j) for j in JEZIKI if j != "sl"))
    slovenske = besede("sl") - tuje
    najdeni = []
    for vrstica, s in _literali(vir):
        golo = re.sub(r"<[^>]+>", " ", s).strip()
        if golo in DOVOLJENI_LITERALI:
            continue
        sumniki = re.search(r"[čšžČŠŽ]", golo)
        if not sumniki and re.fullmatch(r"[a-z0-9_:.#/=\[\]\"'-]+", golo):
            continue          # en identifikator (kljuc, razred CSS, metoda)
        if not sumniki and re.fullmatch(r"[a-z0-9_:-]+( [a-z0-9_:-]+)+", golo) and not re.search(r"\b(je|ni|ki|se|na|za|ali|in)\b", golo):
            continue          # vec razredov CSS (»pripni odstrani«, »ploscica dodaj«)
        if sumniki or any(w.lower() in slovenske for w in re.findall(r"[A-Za-zČŠŽčšž]{3,}", golo)):
            najdeni.append((vrstica, golo[:80]))
    assert najdeni == [], najdeni


def test_prevedi_prevaja_aria_in_dinamicne_dele():
    vir = (OS / "os.js").read_text(encoding="utf-8")
    assert 'el.setAttribute("aria-label", t(el.getAttribute("data-aria")))' in vir
    i = vir.index("  function prevedi() {")
    prevedi = vir[i:vir.index("\n  }\n", i)]
    assert "osveziGumbViri();" in prevedi and "narisiViriFilter();" in prevedi and "prevediV($(\"mediaZanri\"))" in prevedi
    # jezik iz naslova strani v vseh oknih, ne le v oknih razdelkov
    assert 'var jezikUrl = (location.search.match(/[?&]jezik=([a-z]{2})(?:&|$)/) || [])[1];' in vir


def test_jezik_oken_pred_prvim_oknom():
    vir = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
    glavna = vir[vir.index("\ndef main("):]
    assert glavna.index("_nastavi_jezik_oken(_jezik_vmesnika(os_backend_win.nalozi_shrambo()))") < glavna.index("window = SafeerOsWindow(")
    assert '[("jezik", _jezik_oken())]' in vir      # naslov glavne strani in Playerja nosi jezik


def test_imena_iz_podatkov_imajo_kljuc_pod(slovar):
    """Zvrsti, drzave in skupine pridejo iz core/zakoniti_viri.py v slovenscini; os.js izPodatkov() jih prevede."""
    sys.path.insert(0, str(KOREN))
    from core import zakoniti_viri as z
    imena = {v[0] for v in z.GLASBENE_ZVRSTI.values()} | set(z.DRZAVE.values()) | {
        "Najbolj poslušane", "Iskanje", "Javna last", "TuneIn · v bližini"}
    sl = {v: k for k, v in slovar["sl"].items() if k.startswith("pod_")}
    # enaka v vseh jezikih (lastna imena zvrsti)
    enaka = {"Pop", "Rock", "Hip-hop", "Jazz", "Metal", "Reggae", "Country"}
    manjka = sorted(i for i in imena - enaka if i not in sl)
    assert manjka == [], manjka
    vir = (OS / "os.js").read_text(encoding="utf-8")
    assert "b.textContent = izPodatkov(z.ime);" in vir and "ubezi(izPodatkov(mediaZadnjaSkupina))" in vir
