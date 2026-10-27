"""Ciscenje ikon SVG iz tujih virov (katalog Sporocil iz ferdium-recipes) - SAMO dovoljeni elementi in atributi.

Zakaj: ikona tujega izvora gre v vmesnik Safeer OS (<img src="data:image/svg+xml...">). V <img> brskalnik skript v SVG
ne zazene, a ikono lahko kdo vstavi tudi drugam (CSS, vgrajen <svg>, drug pregledovalnik), zato je ociscena ZE v
katalogu, ne sele ob prikazu. Pregled 27. 10. 2026: v ferdium-recipes (commit d606ede) imajo 4 ikone ostanek
<script id="bw-fido2-page-script"> (vrinila ga je razsiritev brskalnika ob shranjevanju), 1 <foreignObject>,
28 <!DOCTYPE> (1 z notranjimi ENTITY), 99 <style> in 46 zunanjih ali data: href.

Pravila (bel seznam - kar ni nasteto, gre ven):
  * elementi: samo risanje (path, g, gradienti, filtri brez feImage ...); script, foreignObject, a, animate/set (lahko
    nastavijo href na javascript:), feImage, iframe, metadata in elementi tujih imenskih prostorov (inkscape, sodipodi,
    Illustrator) se odstranijo s celotnim poddrevesom;
  * atributi: samo nasteti predstavitveni atributi; on* (dogodki), tuji imenski prostori, data-*, aria-* gredo ven;
  * href / xlink:href: samo notranji sklic »#id«; pri <image> se dovoljena slika data:image/png|jpeg|gif|webp;base64;
  * url(...) v atributu ali CSS: samo »url(#id)«; zunanji url() se zamenja z »none«;
  * CSS (<style>, style=""): brez @import, expression(), javascript:, -moz-binding, behavior in brez ubeznic »\\«
    (z njimi bi se dalo skriti »url(«);
  * DOCTYPE: dovoljene so samo preproste notranje ENTITY z dobesedno vrednostjo (Illustrator: &ns_ai; ...); se
    razresijo in DOCTYPE se odstrani. Zunanje (SYSTEM/PUBLIC) ali parametrske (%) entitete -> ikona se zavrne.
  * velikost: vhod najvec NAJVEC_VHOD, izhod najvec NAJVEC_IZHOD bajtov (vecja ikona se zavrne).
Rezultat je idempotenten: ocisti(ocisti(x)) == ocisti(x).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

NAJVEC_VHOD = 5_000_000
NAJVEC_IZHOD = 200_000

DOVOLJENI_ELEMENTI = frozenset("""
svg g path rect circle ellipse line polyline polygon defs symbol use switch title desc style
linearGradient radialGradient stop clipPath mask pattern marker image text tspan textPath
filter feBlend feColorMatrix feComponentTransfer feComposite feFlood feGaussianBlur feMerge feMergeNode feOffset
feFuncA feFuncR feFuncG feFuncB feMorphology feDropShadow
""".split())

#: Elementi, katerih besedilo ostane (drugje je besedilo med elementi samo presledek).
Z_BESEDILOM = frozenset({"title", "desc", "text", "tspan", "textPath", "style"})

DOVOLJENI_ATRIBUTI = frozenset("""
id class style version baseProfile width height x y x1 y1 x2 y2 cx cy r rx ry fx fy fr d points viewBox
preserveAspectRatio transform offset gradientUnits gradientTransform spreadMethod
fill fill-opacity fill-rule stroke stroke-width stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray
stroke-dashoffset stroke-opacity opacity stop-color stop-opacity color display visibility overflow
clip-path clip-rule clipPathUnits mask maskUnits maskContentUnits patternUnits patternContentUnits patternTransform
filter filterUnits primitiveUnits in in2 result operator k1 k2 k3 k4 stdDeviation dx dy flood-color flood-opacity
mode values type tableValues slope intercept amplitude exponent offset radius color-interpolation-filters
color-interpolation enable-background shape-rendering image-rendering text-rendering vector-effect paint-order
mix-blend-mode isolation marker-start marker-mid marker-end markerWidth markerHeight refX refY orient markerUnits
font-family font-size font-weight font-style font-stretch text-anchor dominant-baseline alignment-baseline
baseline-shift letter-spacing word-spacing writing-mode startOffset method spacing lengthAdjust textLength rotate
""".split())

#: Elementi, pri katerih je href (notranji sklic #id) smiseln.
S_SKLICEM = frozenset({"use", "linearGradient", "radialGradient", "pattern", "textPath", "image", "filter"})

_NOTRANJI_SKLIC = re.compile(r"^#[A-Za-z_][\w.:-]{0,200}$")
_SLIKA_DATA = re.compile(r"^data:image/(?:png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$")
_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_NEVARNO_CSS = re.compile(r"expression\s*\(|javascript:|vbscript:|-moz-binding|behavior\s*:|</", re.I)
_IMPORT = re.compile(r"@import[^;]*;?", re.I)
_KOMENTAR_CSS = re.compile(r"/\*.*?\*/", re.S)
_DOCTYPE = re.compile(r"<!DOCTYPE\s+[^\[>]*(\[(?P<podmnozica>.*?)\]\s*)?>", re.S | re.I)
_ENTITETA = re.compile(r"""<!ENTITY\s+([A-Za-z_][\w.-]*)\s+(?:"([^"]*)"|'([^']*)')\s*>""")
_KOMENTAR_XML = re.compile(r"<!--.*?-->", re.S)
_NADZORNI = re.compile(r"[\x00-\x20\x7f]+")


class NevarnaSvg(ValueError):
    """Ikone ni mogoce varno ocistiti (razlog v args[0])."""


def _lokalno(ime: str) -> tuple:
    """'{ns}ime' -> (ns, ime)."""
    if ime.startswith("{"):
        ns, _, lok = ime[1:].partition("}")
        return ns, lok
    return "", ime


def ocisti_css(css: str) -> str:
    """CSS iz <style> ali style="": brez komentarjev in @import, zunanji url() -> none. Ce ostane karkoli nevarnega
    (ali ubeznica, ki bi lahko skrila url), vrne prazen niz."""
    s = _KOMENTAR_CSS.sub("", str(css or ""))
    if "\\" in s or _NEVARNO_CSS.search(s):
        return ""
    s = _IMPORT.sub("", s)
    s = _URL.sub(lambda m: m.group(0) if _NOTRANJI_SKLIC.match(m.group(2).strip()) else "none", s)
    if re.search(r"url\s*\(", s, re.I) and not all(_NOTRANJI_SKLIC.match(m.group(2).strip()) for m in _URL.finditer(s)):
        return ""
    if re.search(r"@import", s, re.I):
        return ""
    return s.strip()


def _varna_vrednost(vrednost: str) -> bool:
    strnjeno = _NADZORNI.sub("", vrednost).lower()
    if "javascript:" in strnjeno or "vbscript:" in strnjeno or "data:" in strnjeno:
        return False
    for m in _URL.finditer(vrednost):
        if not _NOTRANJI_SKLIC.match(m.group(2).strip()):
            return False
    if re.search(r"url\s*\(", vrednost, re.I) and not _URL.search(vrednost):
        return False
    return True


def _razresi_doctype(besedilo: str) -> str:
    m = _DOCTYPE.search(besedilo)
    if m is None:
        if re.search(r"<!(DOCTYPE|ENTITY)", besedilo, re.I):
            raise NevarnaSvg("doctype")
        return besedilo
    podmnozica = _KOMENTAR_XML.sub("", m.group("podmnozica") or "")
    entitete = {}
    for e in _ENTITETA.finditer(podmnozica):
        vrednost = e.group(2) if e.group(2) is not None else e.group(3)
        if any(z in vrednost for z in "&<%"):
            raise NevarnaSvg("entiteta")
        entitete[e.group(1)] = vrednost
    if _ENTITETA.sub("", podmnozica).strip():
        raise NevarnaSvg("entiteta")      # SYSTEM/PUBLIC, parametrska (%), ELEMENT/ATTLIST ...
    if len(entitete) > 64:
        raise NevarnaSvg("entiteta")
    telo = besedilo[:m.start()] + besedilo[m.end():]
    if re.search(r"<!(DOCTYPE|ENTITY)", telo, re.I):
        raise NevarnaSvg("doctype")
    for ime, vrednost in entitete.items():
        sklic = "&%s;" % ime
        if len(telo) + telo.count(sklic) * max(0, len(vrednost) - len(sklic)) > NAJVEC_VHOD:
            raise NevarnaSvg("entiteta")  # razsiritev bi presegla omejitev vhoda (napad »milijarda smehov«)
        telo = telo.replace(sklic, vrednost)
    return telo


def _ocisti_element(star, nov_stars, je_koren=False):
    ns, ime = _lokalno(star.tag) if isinstance(star.tag, str) else ("x", "")
    if ns not in ("", SVG_NS) or ime not in DOVOLJENI_ELEMENTI:
        return None
    if je_koren and ime != "svg":
        return None
    atributi = {}
    for kljuc, vrednost in star.attrib.items():
        ans, aime = _lokalno(kljuc)
        vrednost = str(vrednost)
        if aime.lower().startswith("on"):
            continue
        if aime == "href" and ans in ("", XLINK_NS):
            v = vrednost.strip()
            if ime in S_SKLICEM and _NOTRANJI_SKLIC.match(v):
                atributi[kljuc] = v
            elif ime == "image" and _SLIKA_DATA.match(v):
                atributi[kljuc] = re.sub(r"\s+", "", v)
            continue
        if ans == XML_NS and aime == "space":
            atributi[kljuc] = "preserve" if vrednost == "preserve" else "default"
            continue
        if ans or aime not in DOVOLJENI_ATRIBUTI:
            continue
        if aime == "style":
            vrednost = ocisti_css(vrednost)
            if not vrednost:
                continue
        if not _varna_vrednost(vrednost):
            continue
        atributi[kljuc] = vrednost
    if ime == "image" and not any(_lokalno(k)[1] == "href" for k in atributi):
        return None
    oznaka = "{%s}%s" % (SVG_NS, ime)
    nov = ET.Element(oznaka, atributi) if nov_stars is None else ET.SubElement(nov_stars, oznaka, atributi)
    if ime in Z_BESEDILOM and star.text:
        nov.text = ocisti_css(star.text) if ime == "style" else star.text
    for otrok in list(star):
        ociscen = _ocisti_element(otrok, nov)
        if ociscen is not None and ime in Z_BESEDILOM and otrok.tail:
            ociscen.tail = otrok.tail
    if ime == "style" and not (nov.text or "").strip() and nov_stars is not None:
        nov_stars.remove(nov)      # prazen ali zavrnjen CSS: element <style> ne ostane
        return None
    return nov


def ocisti(svg) -> str:
    """Ocisti ikono SVG (niz ali bajti). Vrne varen SVG kot niz UTF-8 ali sprozi NevarnaSvg."""
    if isinstance(svg, (bytes, bytearray)):
        if len(svg) > NAJVEC_VHOD:
            raise NevarnaSvg("velikost")
        try:
            svg = bytes(svg).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise NevarnaSvg("kodiranje") from None
    besedilo = str(svg or "")
    if not besedilo.strip():
        raise NevarnaSvg("prazno")
    if len(besedilo) > NAJVEC_VHOD:
        raise NevarnaSvg("velikost")
    besedilo = besedilo.lstrip("\ufeff")
    besedilo = re.sub(r"^\s*<\?xml[^>]*\?>", "", besedilo)
    besedilo = _razresi_doctype(besedilo)
    try:
        koren = ET.fromstring(besedilo)
    except ET.ParseError:
        raise NevarnaSvg("xml") from None
    ns, ime = _lokalno(koren.tag)
    if ime != "svg" or ns not in ("", SVG_NS):
        raise NevarnaSvg("koren")
    ociscen = _ocisti_element(koren, None, je_koren=True)
    if ociscen is None:
        raise NevarnaSvg("koren")
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    izhod = ET.tostring(ociscen, encoding="unicode", short_empty_elements=True)
    if len(izhod.encode("utf-8")) > NAJVEC_IZHOD:
        raise NevarnaSvg("velikost")
    return izhod
