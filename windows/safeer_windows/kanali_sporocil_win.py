"""Vgrajeni spletni klepeti v Sporocilih Safeer OS za Windows (lastnik 27. in 28. 10. 2026: »Windows naj ima Sporocila
kot Linux«).

Enako kot Safeer-linux core/os_kanali_sporocil.py, a s Qt namesto GTK:
  * Seznam kanalov je skupna koda core/spletni_klepeti.Kanali (ista shramba kot ostale nastavitve Safeer OS).
  * Spletni kanal je QWebEngineView z LASTNIM profilom (QWebEngineProfile »SafeerKanal-<id>«: piskotki, shramba in
    prijava so loceni po storitvah - npr. dva racuna iste storitve; »Izbrisi podatke« pobrise samo ta profil).
  * Stran Sporocil (HTML) pove pravokotnik vsebine v CSS px; pogled kanala je otrok pogleda strani na tem mestu
    (merilo = zoomFactor strani). Ko je odprt sloj strani (pogovorno okno, meni), stran kanal skrije.
  * Neprebrano: naslov strani (spletni_klepeti.neprebrano); zadnje znano stevilo se shrani v seznam kanalov, da je
    znacka pravilna ze ob zagonu (namizje Windows jo bere prek »sporocilaSeznam« + »kanaliSeznam«).
  * Namizni programi (Viber, Signal Desktop) se na Windows ne vstavljajo v okno: katalog jih ne ponudi.
  * Kanali se nalozijo ob zagonu (zaporedoma po HKRATI_OB_ZAGONU) in tecejo ves cas; izklopljen kanal se sprosti.

Vse metode, ki ustvarjajo ali premikajo poglede, tecejo v glavni niti Qt (klicatelj: os_app._na_glavni_niti).
Qt je za tem vmesnikom (Pogledi): logika je preizkusljiva brez Qt (windows/tests/test_kanali_sporocil_win.py).
"""
from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from typing import Any

from core import katalog_storitev, spletni_klepeti

#: Najvec kanalov, ki se hkrati nalagajo ob zagonu (kot Linux).
HKRATI_OB_ZAGONU = 2
#: Ce kanal ne javi konca nalaganja, naslednji pride na vrsto po tem casu.
NALAGANJE_NAJDLJE_S = 12


def ime_profila(kid: str) -> str:
    """Ime trajnega profila QWebEngine za kanal: samo crke, stevke, - in _ (ime gre v pot na disku)."""
    cisto = re.sub(r"[^A-Za-z0-9_-]", "_", str(kid or ""))[:64]
    return "SafeerKanal-" + (cisto or "kanal")


def pravokotnik(r: Any, merilo: float) -> tuple | None:
    """CSS px strani (x, y, w, h) -> logicne tocke Qt v pogledu strani (x, y, sirina, visina); None ob napacnem vnosu."""
    if not isinstance(r, dict):
        return None
    try:
        x, y, w, h = (float(r.get(k) or 0) for k in ("x", "y", "w", "h"))
        m = float(merilo or 1)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and abs(v) < 1e6 for v in (x, y, w, h, m)) or m <= 0:   # NaN ali neumne vrednosti
        return None
    return (max(0, round(x * m)), max(0, round(y * m)), max(0, round(w * m)), max(0, round(h * m)))


class _Kanal:
    def __init__(self, podatki: dict) -> None:
        self.podatki = podatki
        self.pogled = None          # objekt Pogledi.ustvari (QWebEngineView)
        self.nalozen = False


class KanaliSporocilWin:
    def __init__(self, pogledi, shramba, jezik: Callable[[], str], dogodek: Callable[[str, Any], None],
                 cas: Callable[[], float] = time.monotonic) -> None:
        """pogledi: ustvari(kid, url, ob_naslovu, ob_nalozeno) -> pogled, pokazi(pogled, gostitelj, pravokotnik),
        skrij(pogled), unici(pogled), izbrisi_podatke(pogled, ob_koncu), ukaz(pogled, ukaz, url) -> bool,
        merilo(gostitelj) -> float, zakasni(ms, fn)."""
        self.pogledi = pogledi
        self.kanali = spletni_klepeti.Kanali(shramba)
        self.jezik, self.dogodek, self.cas = jezik, dogodek, cas
        self.zivi: dict[str, _Kanal] = {}
        #: id(pogled strani) -> kid kanala, ki je trenutno prikazan nad njo
        self.prikazan: dict[int, str] = {}
        self._vrsta: list = []
        self._nalaga: set = set()
        self.casi: dict[str, dict] = {}

    # ------------------------------------------------------------------ stanje
    def seznam(self) -> list:
        izid = []
        for k in self.kanali.seznam():
            z = self.zivi.get(k["id"])
            vnos = spletni_klepeti.po_id(k["katalog"]) or {}
            program = spletni_klepeti.je_program(vnos)
            d = dict(k, vrsta="program" if program else "splet", nalozen=bool(z and z.nalozen),
                     vgrajeno=not program, namescen=False, ikona="")
            if not program and k.get("url"):
                d["ikona"] = katalog_storitev.ikona(k["katalog"])
            izid.append(d)
        return izid

    def katalog(self) -> list:
        """Katalog za carovnik brez namiznih programov (na Windows jih ne vstavljamo). Odprtje kataloga ne klice strani
        storitev (ikone so iz core/katalog_storitev, ze na disku)."""
        izid = []
        for v in spletni_klepeti.za_vmesnik(self.jezik()):
            if spletni_klepeti.je_program(v):
                continue
            v = dict(v, ikona="")
            if v.get("splet"):
                v["ikona"] = katalog_storitev.ikona(v["id"])
            izid.append(v)
        return izid

    def neprebrano_skupaj(self) -> int:
        return sum(int(k.get("neprebrano") or 0) for k in self.kanali.seznam() if k.get("vklopljen"))

    def _sporoci(self) -> None:
        try:
            self.dogodek("kanaliSporocil", self.seznam())
        except Exception as e:  # noqa: BLE001
            print("[Sporocila] dogodek kanalov:", e, flush=True)

    # ------------------------------------------------------------------ urejanje (most strani)
    def dodaj(self, katalog: str = "", url: str = "", ime: str = "", pot: str = "") -> list:
        vnos = spletni_klepeti.po_id(katalog) if katalog else None
        if pot or (vnos is not None and spletni_klepeti.je_program(vnos)):
            raise ValueError("program")        # namizni programi se na Windows ne vstavljajo
        k = self.kanali.dodaj(katalog=katalog, url=url, ime_kanala=ime, jezik=self.jezik(), pot="")
        self._ustvari(k)
        self._sporoci()
        return self.seznam()

    def odstrani(self, kid: str, izbrisi_podatke: bool = False) -> list:
        z = self.zivi.get(kid)
        if z is not None and izbrisi_podatke and z.pogled is not None:
            self.pogledi.izbrisi_podatke(z.pogled, None)
        self._unici(kid)
        self.kanali.odstrani(kid)
        self._sporoci()
        return self.seznam()

    def preklici(self, kid: str) -> list:
        k = self.kanali.najdi(kid)
        if k is None:
            return self.seznam()
        if not k.get("caka"):
            raise ValueError("v_uporabi")
        return self.odstrani(kid, False)

    def preimenuj(self, kid: str, ime: str) -> list:
        self.kanali.preimenuj(kid, ime)
        self._sporoci()
        return self.seznam()

    def premakni(self, kid: str, smer: int) -> list:
        self.kanali.premakni(kid, smer)
        self._sporoci()
        return self.seznam()

    def vklopi(self, kid: str, vklopljen: bool) -> list:
        k = self.kanali.vklopi(kid, bool(vklopljen))
        if vklopljen:
            self._ustvari(k)
        else:
            self._unici(kid)
            self.kanali.zapomni_neprebrano(kid, 0)
        self._sporoci()
        return self.seznam()

    def izbrisi_podatke(self, kid: str) -> list:
        """Prijava, shramba in predpomnilnik profila tega kanala; kanal se nalozi znova (na prijavo)."""
        k = self.kanali.najdi(kid)
        if k is None or not k.get("url"):
            raise ValueError("kanal")
        z = self.zivi.get(kid) or self._ustvari(k)
        if z is not None and z.pogled is not None:
            self.pogledi.izbrisi_podatke(z.pogled, lambda: self.pogledi.ukaz(z.pogled, "domov", k["url"]))
        return self.seznam()

    # ------------------------------------------------------------------ nalaganje ob zagonu
    def zazeni_vse(self) -> None:
        self._vrsta = [k["id"] for k in self.kanali.seznam() if k.get("vklopljen") and k["id"] not in self.zivi]
        self._naslednji()

    def _naslednji(self) -> None:
        while self._vrsta and len(self._nalaga) < HKRATI_OB_ZAGONU:
            kid = self._vrsta.pop(0)
            self._nalaga.add(kid)
            k = self.kanali.najdi(kid)
            if k is not None and k.get("vklopljen"):
                self._ustvari(k)
            else:
                self._nalozeno(kid)
                continue
            self.pogledi.zakasni(NALAGANJE_NAJDLJE_S * 1000, lambda kid=kid: self._nalozeno(kid))

    def _nalozeno(self, kid: str) -> None:
        if kid in self._nalaga:
            self._nalaga.discard(kid)
            self._naslednji()

    # ------------------------------------------------------------------ ustvarjanje in unicenje
    def _ustvari(self, k: dict) -> _Kanal | None:
        if k["id"] in self.zivi:
            return self.zivi[k["id"]]
        vnos = spletni_klepeti.po_id(k.get("katalog", "")) or {}
        if spletni_klepeti.je_program(vnos) or not k.get("url"):
            self._nalozeno(k["id"])
            return None
        kid = k["id"]
        z = _Kanal(k)
        self.casi[kid] = {"zacetek": self.cas()}
        z.pogled = self.pogledi.ustvari(kid, k["url"], lambda n, kid=kid: self._naslov(kid, n),
                                        lambda ok, kid=kid: self._ob_nalozeno(kid, ok))
        self.zivi[kid] = z
        return z

    def _ob_nalozeno(self, kid: str, ok: bool) -> None:
        z = self.zivi.get(kid)
        if z is None or z.nalozen or not ok:
            return
        z.nalozen = True
        c = self.casi.get(kid)
        if c is not None and "vsebina_s" not in c:
            c["vsebina_s"] = round(self.cas() - c["zacetek"], 2)
        self._nalozeno(kid)
        self._sporoci()

    def _naslov(self, kid: str, naslov: str) -> None:
        if kid in self.zivi and self.kanali.zapomni_neprebrano(kid, spletni_klepeti.neprebrano(naslov)):
            self._sporoci()

    def _unici(self, kid: str) -> None:
        z = self.zivi.pop(kid, None)
        self._nalaga.discard(kid)
        if kid in self._vrsta:
            self._vrsta.remove(kid)
        for gid, prikazani in list(self.prikazan.items()):
            if prikazani == kid:
                self.prikazan.pop(gid, None)
        if z is not None and z.pogled is not None:
            self.pogledi.unici(z.pogled)

    # ------------------------------------------------------------------ mesto nad stranjo
    def pokazi(self, gostitelj, kid: str, r: dict) -> dict:
        k = self.kanali.najdi(kid)
        if k is None or not k.get("vklopljen"):
            return {"ok": False, "razlog": "kanal"}
        z = self.zivi.get(kid) or self._ustvari(k)
        if z is None or z.pogled is None:
            vnos = spletni_klepeti.po_id(k.get("katalog", "")) or {}
            return {"ok": False, "razlog": "program" if spletni_klepeti.je_program(vnos) else "splet"}
        prej = self.prikazan.get(id(gostitelj))
        if prej and prej != kid and prej in self.zivi:
            self.pogledi.skrij(self.zivi[prej].pogled)
        p = pravokotnik(r, self.pogledi.merilo(gostitelj))
        if p is None:
            return {"ok": False, "razlog": "polozaj"}
        self.prikazan[id(gostitelj)] = kid
        self.pogledi.pokazi(z.pogled, gostitelj, p)
        return {"ok": True, "vgrajeno": True}

    def polozaj(self, gostitelj, r: dict) -> bool:
        kid = self.prikazan.get(id(gostitelj))
        z = self.zivi.get(kid or "")
        p = pravokotnik(r, self.pogledi.merilo(gostitelj))
        if z is None or z.pogled is None or p is None:
            return False
        self.pogledi.pokazi(z.pogled, gostitelj, p)
        return True

    def skrij(self, gostitelj) -> bool:
        kid = self.prikazan.pop(id(gostitelj), None)
        z = self.zivi.get(kid or "")
        if z is None:
            return False
        # Uporabnik je zapustil kanal, ki je na svoji strani (prijavljen): zdaj je v uporabi, brez »Preklici«.
        k = self.kanali.najdi(kid)
        if k is not None and k.get("caka") and z.pogled is not None and \
                spletni_klepeti.ista_stran(self.pogledi.naslov(z.pogled) or "", k.get("url") or "") and \
                self.kanali.potrdi(kid):
            self._sporoci()
        if z.pogled is not None:
            self.pogledi.skrij(z.pogled)
        return True

    def ukaz(self, kid: str, ukaz: str) -> bool:
        z = self.zivi.get(kid)
        if z is None or z.pogled is None or ukaz not in ("nazaj", "osvezi", "domov", "splet"):
            return False
        return bool(self.pogledi.ukaz(z.pogled, ukaz, z.podatki.get("url") or ""))

    def koncaj(self) -> None:
        for kid in list(self.zivi):
            self._unici(kid)


# ---------------------------------------------------------------------------------------------- Qt (samo Windows)
try:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QWidget
    _QT = True
except ImportError:  # pragma: no cover - preizkusi brez QtWebEngine
    _QT = False


class _StranKanala(QWebEnginePage if _QT else object):  # type: ignore[misc]
    """Stran kanala: povezave na drugo stran (target=_blank) gredo v Splet Safeer OS, ne v novo okno kanala."""

    def __init__(self, profil, starsevski, odpri_zunaj: Callable[[str], Any]) -> None:
        super().__init__(profil, starsevski)
        self._odpri_zunaj = odpri_zunaj

    def createWindow(self, _vrsta):
        zacasna = QWebEnginePage(self.profile(), self)

        def naprej(url) -> None:
            u = url.toString()
            if u.startswith(("http://", "https://")):
                self._odpri_zunaj(u)
            zacasna.deleteLater()
        zacasna.urlChanged.connect(naprej)
        return zacasna


class QtPogledi:
    """Pogledi Qt za KanaliSporocilWin. Skriti pogledi so v nevidnem zabojniku (strani tecejo naprej)."""

    def __init__(self, odpri_zunaj: Callable[[str], Any], obvestilo: Callable[[str, str, str], Any]) -> None:
        self._zaboj = QWidget()
        self._zaboj.hide()
        self._odpri_zunaj = odpri_zunaj
        self._obvestilo = obvestilo
        self._profili: dict[str, Any] = {}

    def _profil(self, kid: str):
        ime = ime_profila(kid)
        p = self._profili.get(ime)
        if p is None:
            p = QWebEngineProfile(ime, self._zaboj)      # trajen: piskotki in shramba na disku, loceno po kanalu
            p.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            try:
                p.setNotificationPresenter(lambda obv, kid=kid: self._obvestilo(kid, obv.title(), obv.message()))
            except Exception as e:  # noqa: BLE001 - starejsi Qt brez predstavitelja obvestil
                print("[Sporocila] obvestila kanala:", e, flush=True)
            self._profili[ime] = p
        return p

    def ustvari(self, kid: str, url: str, ob_naslovu, ob_nalozeno):
        pogled = QWebEngineView(self._zaboj)
        stran = _StranKanala(self._profil(kid), pogled, self._odpri_zunaj)
        stran.titleChanged.connect(lambda n: ob_naslovu(str(n or "")))
        stran.loadFinished.connect(lambda ok: ob_nalozeno(bool(ok)))
        pogled.setPage(stran)
        pogled.hide()
        pogled.load(QUrl(url))
        return pogled

    def merilo(self, gostitelj) -> float:
        try:
            return float(gostitelj.zoomFactor() or 1)
        except Exception:  # noqa: BLE001
            return 1.0

    def pokazi(self, pogled, gostitelj, p: tuple) -> None:
        if pogled.parent() is not gostitelj:
            pogled.setParent(gostitelj)
        pogled.setGeometry(*p)
        pogled.show()
        pogled.raise_()
        pogled.setFocus()

    def skrij(self, pogled) -> None:
        pogled.hide()
        if pogled.parent() is not self._zaboj:
            pogled.setParent(self._zaboj)

    def unici(self, pogled) -> None:
        stran = pogled.page()
        pogled.hide()
        pogled.setParent(None)
        try:
            stran.deleteLater()
        except Exception as e:  # noqa: BLE001
            print("[Sporocila] unici stran kanala:", e, flush=True)
        pogled.deleteLater()

    def izbrisi_podatke(self, pogled, ob_koncu) -> None:
        profil = pogled.page().profile()
        profil.clearHttpCache()
        profil.cookieStore().deleteAllCookies()
        try:
            profil.clearAllVisitedLinks()
        except Exception as e:  # noqa: BLE001
            print("[Sporocila] obiskane povezave kanala:", e, flush=True)
        if ob_koncu is not None:
            QTimer.singleShot(300, ob_koncu)

    def naslov(self, pogled) -> str:
        try:
            return pogled.url().toString()
        except Exception:  # noqa: BLE001
            return ""

    def ukaz(self, pogled, ukaz: str, url: str) -> bool:
        if ukaz == "nazaj":
            pogled.back()
        elif ukaz == "osvezi":
            pogled.reload()
        elif ukaz == "domov":
            pogled.load(QUrl(url))
        elif ukaz == "splet":
            self._odpri_zunaj(self.naslov(pogled) or url)
        else:
            return False
        return True

    def zakasni(self, ms: int, fn) -> None:
        QTimer.singleShot(int(ms), fn)
