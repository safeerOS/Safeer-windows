"""Vnos iz okna gledalca deljenega zaslona (telefon, tablica) - miska, tipkovnica, kolesce, odlozisce -> Safeer Vnos.

Lastnik, 25. 10. 2026: na Windows se je zaslon telefona (»Odpri tukaj«) odprl kot zavihek Spleta in miska ter
tipkovnica aplikacije na telefonu nista upravljali. Na Linuxu ima gledalec svoje okno (safeer_control.py
GLEDALEC_VNOS_JS); ta modul je ista logika brez GTK/Qt, da jo uporabljata obe platformi:

- skripta(poslji_js, jezik): JavaScript, ki ga okno vbrizga v LOCEN svet skript (stran s sredisca do mostu ne seze) in
  ki uposteva samo dogodke uporabnika (e.isTrusted). `poslji_js` je telo funkcije poslji(d, p) - prenos je stvar
  platforme (WebKitGTK messageHandlers, Qt WebEngine izpis z zetonom);
- preveri(sporocilo): kar pride iz skripte -> (dejanje, parametri) z omejenimi vrednostmi ali None;
- velikost_okna(...): okno v obliki slike naprave in cim vecje (pokoncen telefon zapolni visino);
- odziv(...): kaj naj okno pove, ko naprava vnosa ne sprejme (npr. Safeer Vnos ni vklopljen).

Na napravi vnos izvede Safeer Vnos (storitev dostopnosti, ki jo uporabnik vklopi sam): Android Daljinec.kt
`input.tap|swipe|key|text|scroll|enable`, tipke VnosStoritev.tipka.
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

#: Dejanja, ki jih okno gledalca sme poslati napravi (vse drugo zavrne ze racunalnik).
DEJANJA = ("input.tap", "input.swipe", "input.key", "input.text", "input.scroll", "input.enable")
#: Tipke, ki jih Safeer Vnos zna (Android VnosStoritev.tipka).
TIPKE = ("back", "home", "recents", "notifications", "up", "down", "left", "right", "enter", "backspace", "delete")
#: Dejanja okna (ne gredo na napravo): velikost slike in lepljenje iz odlozisca racunalnika.
DEJANJA_OKNA = ("okno.velikost", "odlozisce.prilepi")
NAJVEC_BESEDILA = 2000          # Android Daljinec: p.optString("text").take(2000)
NAJVEC_KORAKOV = 10

BESEDILA = {
    "sl": {"nazaj": "Nazaj", "domov": "Domov", "opravila": "Odprte aplikacije", "obvestila": "Obvestila",
           "celozaslonsko": "Celozaslonsko (F11)", "zapri": "Zapri", "zaslon": "Zaslon",
           "vnosNi": "Za upravljanje z miško in tipkovnico na napravi vklopi Safeer Vnos – gumb »Odpri "
                     "nastavitve na napravi« odpre pravo stran.",
           "niDovoljeno": "Naprava upravljanja s tega računalnika ne dovoli. Na napravi v Safeer Linku dodaj ta"
                          " računalnik v ožji krog.",
           "odpriNastavitve": "Odpri nastavitve na napravi", "vnosNiUspel": "Naprava vnosa ni izvedla.",
           "nastavitveOdprte": "Na napravi so se odprle nastavitve dostopnosti – vklopi Safeer Vnos."},
    "en": {"nazaj": "Back", "domov": "Home", "opravila": "Recent apps", "obvestila": "Notifications",
           "celozaslonsko": "Full screen (F11)", "zapri": "Close", "zaslon": "Screen",
           "vnosNi": "To control the device with your mouse and keyboard, turn on Safeer Vnos on it – the "
                     "“Open settings on the device” button opens the right page.",
           "niDovoljeno": "The device does not allow control from this computer. On the device, add this "
                          "computer to the inner circle in Safeer Link.",
           "odpriNastavitve": "Open settings on the device", "vnosNiUspel": "The device did not carry out the input.",
           "nastavitveOdprte": "Accessibility settings opened on the device – turn on Safeer Vnos."},
    "de": {"nazaj": "Zurück", "domov": "Start", "opravila": "Letzte Apps", "obvestila": "Benachrichtigungen",
           "celozaslonsko": "Vollbild (F11)", "zapri": "Schließen", "zaslon": "Bildschirm",
           "vnosNi": "Um das Gerät mit Maus und Tastatur zu steuern, schalte dort Safeer Vnos ein – die "
                     "Schaltfläche „Einstellungen auf dem Gerät öffnen“ öffnet die richtige Seite.",
           "niDovoljeno": "Das Gerät erlaubt keine Steuerung von diesem Computer. Füge diesen Computer auf dem "
                          "Gerät in Safeer Link zum engeren Kreis hinzu.",
           "odpriNastavitve": "Einstellungen auf dem Gerät öffnen", "vnosNiUspel": "Das Gerät hat die Eingabe nicht ausgeführt.",
           "nastavitveOdprte": "Auf dem Gerät wurden die Bedienungshilfen geöffnet – schalte Safeer Vnos ein."},
    "es": {"nazaj": "Atrás", "domov": "Inicio", "opravila": "Apps recientes", "obvestila": "Notificaciones",
           "celozaslonsko": "Pantalla completa (F11)", "zapri": "Cerrar", "zaslon": "Pantalla",
           "vnosNi": "Para controlar el dispositivo con el ratón y el teclado, activa en él Safeer Vnos: "
                     "el botón «Abrir ajustes en el dispositivo» abre la página correcta.",
           "niDovoljeno": "El dispositivo no permite el control desde este ordenador. En el dispositivo, añade "
                          "este ordenador al círculo cercano en Safeer Link.",
           "odpriNastavitve": "Abrir ajustes en el dispositivo", "vnosNiUspel": "El dispositivo no realizó la acción.",
           "nastavitveOdprte": "Se abrieron los ajustes de accesibilidad en el dispositivo: activa Safeer Vnos."},
    "fr": {"nazaj": "Retour", "domov": "Accueil", "opravila": "Applis récentes", "obvestila": "Notifications",
           "celozaslonsko": "Plein écran (F11)", "zapri": "Fermer", "zaslon": "Écran",
           "vnosNi": "Pour piloter l’appareil avec la souris et le clavier, active Safeer Vnos dessus : le"
                     " bouton « Ouvrir les paramètres sur l’appareil » ouvre la bonne page.",
           "niDovoljeno": "L’appareil n’autorise pas le contrôle depuis cet ordinateur. Sur l’appareil, ajoute "
                          "cet ordinateur au cercle proche dans Safeer Link.",
           "odpriNastavitve": "Ouvrir les paramètres sur l’appareil", "vnosNiUspel": "L’appareil n’a pas exécuté la saisie.",
           "nastavitveOdprte": "Les paramètres d’accessibilité se sont ouverts sur l’appareil : active Safeer Vnos."},
    "it": {"nazaj": "Indietro", "domov": "Home", "opravila": "App recenti", "obvestila": "Notifiche",
           "celozaslonsko": "Schermo intero (F11)", "zapri": "Chiudi", "zaslon": "Schermo",
           "vnosNi": "Per controllare il dispositivo con mouse e tastiera, attiva Safeer Vnos: il pulsante"
                     " «Apri le impostazioni sul dispositivo» apre la pagina giusta.",
           "niDovoljeno": "Il dispositivo non consente il controllo da questo computer. Sul dispositivo, "
                          "aggiungi questo computer alla cerchia ristretta in Safeer Link.",
           "odpriNastavitve": "Apri le impostazioni sul dispositivo", "vnosNiUspel": "Il dispositivo non ha eseguito l’input.",
           "nastavitveOdprte": "Sul dispositivo si sono aperte le impostazioni di accessibilità: attiva Safeer Vnos."},
}


def t(kljuc: str, jezik: str = "sl") -> str:
    return BESEDILA.get(jezik, BESEDILA["en"]).get(kljuc) or BESEDILA["en"].get(kljuc, kljuc)


_SKRIPTA = r"""
(function () {
  function poslji(d, p) {
    __POSLJI__
  }
  function delez(img, x, y) {
    var r = img.getBoundingClientRect();
    var nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
    var m = Math.min(r.width / nw, r.height / nh);
    var w = nw * m, h = nh * m;
    var ox = r.left + (r.width - w) / 2, oy = r.top + (r.height - h) / 2;
    var fx = (x - ox) / w, fy = (y - oy) / h;
    if (fx < 0 || fy < 0 || fx > 1 || fy > 1) return null;
    return {x: fx, y: fy};
  }
  function slika() { return document.getElementById("zaslon"); }
  // Stran s sredisca ima na sliki svoje poslusalce (dotik poslje sama): dogodek ustavimo v fazi zajema, da gre en klik
  // na napravo enkrat - po Safeer Linku, z odgovorom (npr. »Safeer Vnos ni vklopljen«), ki ga okno pokaze.
  // Tipke gredo napravi sele po prvem kliku uporabnika v okno (pregled 25. 10. 2026, S1): okno, ki se je odprlo samo
  // (deljenje z naprave), ne sme prestreci tipk, ki jih je uporabnik tipkal drugam.
  var zacetek = null, cas = 0, tipkano = "", casovnik = null, kolo = 0, kliknjeno = false;
  document.addEventListener("mousedown", function (e) {
    var img = slika();
    if (!e.isTrusted || !img || e.button !== 0) return;
    kliknjeno = true;
    zacetek = delez(img, e.clientX, e.clientY); cas = Date.now();
    e.preventDefault(); e.stopPropagation();
  }, true);
  document.addEventListener("mouseup", function (e) {
    var img = slika();
    if (!e.isTrusted || !img || e.button !== 0) return;
    e.stopPropagation();
    if (!zacetek) return;
    var konec = delez(img, e.clientX, e.clientY) || zacetek;
    var trajanje = Math.max(60, Math.min(1500, Date.now() - cas));
    if (Math.abs(konec.x - zacetek.x) + Math.abs(konec.y - zacetek.y) > 0.02) {
      poslji("input.swipe", {x1: zacetek.x, y1: zacetek.y, x2: konec.x, y2: konec.y, ms: trajanje});
    } else {
      poslji("input.tap", {x: zacetek.x, y: zacetek.y, ms: trajanje > 450 ? 700 : 60});
    }
    zacetek = null;
  }, true);
  document.addEventListener("wheel", function (e) {
    var img = slika();
    if (!e.isTrusted || !img) return;
    var t = delez(img, e.clientX, e.clientY);
    e.preventDefault();
    if (!t) return;
    // Kolesce: korak na zarezo (120); dotik Safeer Vnos pomakne vsebino pod misko in se na koncu ustavi.
    kolo += e.deltaY;
    var koraki = Math.trunc(kolo / 100);
    if (!koraki && Math.abs(e.deltaY) >= 1 && Math.abs(kolo) >= 40) koraki = kolo > 0 ? 1 : -1;
    if (!koraki) return;
    kolo = 0;
    poslji("input.scroll", {x: t.x, y: t.y, steps: Math.max(-__KORAKI__, Math.min(__KORAKI__, koraki))});
  }, {capture: true, passive: false});
  document.addEventListener("contextmenu", function (e) {
    if (!e.isTrusted) return;
    e.preventDefault(); poslji("input.key", {key: "back"});
  }, true);
  var zadnja = "";
  setInterval(function () {
    var img = slika();
    if (!img || !img.naturalWidth) return;
    var v = img.naturalWidth + "x" + img.naturalHeight;
    if (v !== zadnja) { zadnja = v; poslji("okno.velikost", {w: img.naturalWidth, h: img.naturalHeight}); }
  }, 700);
  var TIPKE = {ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Enter: "enter",
               Backspace: "backspace", Delete: "delete", Escape: "back", BrowserBack: "back", Home: "home"};
  function izprazni() { clearTimeout(casovnik); if (tipkano) poslji("input.text", {text: tipkano}); tipkano = ""; }
  document.addEventListener("keydown", function (e) {
    if (!e.isTrusted || !slika() || !kliknjeno) return;      // samo na strani z zaslonom, po prvem kliku
    if (e.key === "F11") return;                              // celozaslonsko okno (racunalnik)
    // AltGr (@ € { } [ ] \ | ~ na slovenski tipkovnici): Chromium na Windows javi ctrlKey in altKey hkrati (S2).
    var altgr = !!(e.getModifierState && e.getModifierState("AltGraph"));
    var ctrl = (e.ctrlKey || e.metaKey) && !altgr, alt = e.altKey && !altgr;
    if (ctrl && !alt && (e.key === "v" || e.key === "V")) {
      izprazni(); poslji("odlozisce.prilepi", {}); e.preventDefault(); return;
    }
    if (TIPKE[e.key] && !ctrl && !alt) {
      izprazni(); poslji("input.key", {key: TIPKE[e.key]}); e.preventDefault(); return;
    }
    if (e.key.length === 1 && !ctrl && !alt) {
      tipkano += e.key; e.preventDefault();
      clearTimeout(casovnik);
      casovnik = setTimeout(izprazni, 250);
    }
  }, true);
})();
"""


def skripta(poslji_js: str) -> str:
    """JavaScript za okno gledalca; `poslji_js` je telo funkcije poslji(d, p) (d = dejanje, p = parametri)."""
    return _SKRIPTA.replace("__POSLJI__", poslji_js).replace("__KORAKI__", str(NAJVEC_KORAKOV))


def _delez(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    if v != v or v < 0.0 or v > 1.0:                 # NaN ali zunaj slike
        return None
    return round(v, 5)


def _ms(v, najmanj: int, najvec: int, privzeto: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return privzeto
    return int(max(najmanj, min(najvec, v)))


def preveri(sporocilo) -> Optional[Tuple[str, dict]]:
    """Sporocilo skripte ({"d": dejanje, "p": parametri} ali JSON niz) -> (dejanje, cisti parametri) ali None."""
    if isinstance(sporocilo, str):
        try:
            sporocilo = json.loads(sporocilo)
        except ValueError:
            return None
    if not isinstance(sporocilo, dict):
        return None
    d = str(sporocilo.get("d") or "")
    p = sporocilo.get("p") if isinstance(sporocilo.get("p"), dict) else {}
    if d == "okno.velikost":
        w, h = p.get("w"), p.get("h")
        if isinstance(w, int) and isinstance(h, int) and not isinstance(w, bool) and 0 < w <= 16384 and 0 < h <= 16384:
            return d, {"w": w, "h": h}
        return None
    if d == "odlozisce.prilepi":
        return d, {}
    if d not in DEJANJA:
        return None
    if d == "input.tap":
        x, y = _delez(p.get("x")), _delez(p.get("y"))
        return (d, {"x": x, "y": y, "ms": _ms(p.get("ms"), 20, 2000, 60)}) if x is not None and y is not None else None
    if d == "input.swipe":
        t = [_delez(p.get(k)) for k in ("x1", "y1", "x2", "y2")]
        if any(v is None for v in t):
            return None
        return d, {"x1": t[0], "y1": t[1], "x2": t[2], "y2": t[3], "ms": _ms(p.get("ms"), 40, 3000, 300)}
    if d == "input.scroll":
        x, y = _delez(p.get("x")), _delez(p.get("y"))
        koraki = p.get("steps")
        if x is None or y is None or isinstance(koraki, bool) or not isinstance(koraki, int) or koraki == 0:
            return None
        return d, {"x": x, "y": y, "steps": max(-NAJVEC_KORAKOV, min(NAJVEC_KORAKOV, koraki))}
    if d == "input.key":
        k = str(p.get("key") or "")
        return (d, {"key": k}) if k in TIPKE else None
    if d == "input.text":
        b = p.get("text")
        if not isinstance(b, str) or not b:
            return None
        return d, {"text": b[:NAJVEC_BESEDILA]}
    return d, {}                                      # input.enable


def besedilo_iz_odlozisca(besedilo) -> Optional[dict]:
    """Odlozisce racunalnika -> parametri input.text (prazno ali ne-besedilo: nic)."""
    if not isinstance(besedilo, str):
        return None
    besedilo = besedilo.replace("\r\n", "\n")
    return {"text": besedilo[:NAJVEC_BESEDILA]} if besedilo else None


def velikost_okna(sirina: int, visina: int, obmocje: Tuple[int, int, int, int], rob_zgoraj: int = 40,
                  delez: float = 0.94, najmanj_sirina: int = 320) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, sirina, visina) okna v obliki slike naprave, cim vecje na delovnem obmocju (x, y, s, v); None, ce
    podatki niso veljavni. Pokoncen telefon zapolni visino, lezec zaslon sirino (kot Linux _prilagodi_gledalca)."""
    try:
        w, h = int(sirina), int(visina)
        gx, gy, gs, gv = (int(v) for v in obmocje)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or gs <= 0 or gv <= 0:
        return None
    najvec_v, najvec_s = int(gv * delez) - rob_zgoraj, int(gs * delez)
    merilo = min(najvec_v / h, najvec_s / w)
    nova_s, nova_v = max(najmanj_sirina, int(w * merilo)), max(240, int(h * merilo) + rob_zgoraj)
    return gx + (gs - nova_s) // 2, gy + max(0, (gv - nova_v) // 2), nova_s, nova_v


def odziv(odgovor: dict, jezik: str = "sl") -> Tuple[str, bool]:
    """Odgovor naprave na vnos -> (opozorilo za okno, ali pokazati gumb »Odpri nastavitve na napravi«).
    ("", False) = vse v redu (opozorilo se skrije)."""
    if not isinstance(odgovor, dict):
        return "", False
    koda = str(odgovor.get("koda") or odgovor.get("code") or "")
    if odgovor.get("ok"):
        return "", False
    if koda == "vnos_ni_vklopljen":
        return t("vnosNi", jezik), True
    if koda in ("ni_dovoljeno", "ni_ozji_krog", "ni_v_ozjem_krogu", "dovoljenje_potrebno"):
        # Naprava (Android Daljinec.zavrnitevDostopa, OzjiKrogPravila) ali racunalnik upravljanja ni odprl: stavek,
        # kaj narediti, ne oznaka (lastnik, 25. 10. 2026: ena privolitev - ozji krog na napravi odpre upravljanje).
        return t("niDovoljeno", jezik), False
    if koda in ("potrebno_dovoljenje_obracanje",):
        return str(odgovor.get("sporocilo") or odgovor.get("message") or ""), False
    return t("vnosNiUspel", jezik), False
