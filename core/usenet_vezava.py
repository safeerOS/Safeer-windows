"""Vezava lastnega ponudnika Usenet v Safeer OS za Linux (naloga 114; lastnik 27. 10. 2026).

Usenet korak 3 (core/usenet_ponudnik.py) je imel pravila brez vmesnika. Ta modul je most med stranjo Safeer OS
(okno »Moji viri -> Usenet ponudnik«, klic mostu mediaUsenetPonudnik) in jedrom ter predvajanje NZB prek lastnega
pogona (usenet_bralnik + usenet_streznik na 127.0.0.1 z zetonom) - brez TorBoxa, ce ima uporabnik svojega ponudnika.
Enako kot okno na Androidu (naloga 111) in Windows (naloga 112):

- Geslo gre samo iz polja v core/usenet_ponudnik.shrani_ponudnika (sistemska zbirka, core/sporocila/skrivnosti.py).
  Stran ga nikoli ne dobi nazaj; »Preveri« ga bere iz zbirke (preveri_shranjenega), ne s strani.
- Odgovor strani je vedno slovar s KODO (kljuc besedila v assets/os/besedila.js: »unpKoda_« + koda), nikoli besedilo
  izjeme: ta bi lahko nosila vnos (safeer_os.py napako izpise v dnevnik in jo vrne strani).
- Preverba samo na klik, nikoli na glavni niti (most jo klice iz delovne niti; jedro na glavni niti vrze), najvec
  1/min na racun, zapah po zavrnjeni prijavi, TLS s preverbo potrdila - vse v jedru, tu se nic ne obide.
- En film naenkrat: novo predvajanje najprej zapre prejsnji streznik, sele nato vzame bazen racuna (en zivi bazen na
  racun, trda meja povezav). Ko se zadnji streznik zapre (konec, nedejavnost, »Pozabi«), se zapre tudi bazen.
- Ozji krog: za_krog() da zapis BREZ gesla (core/viri_sink.cist_usenet), ki gre samo napravam v ozjem krogu (del
  »ozji« v viri_za_naprave.json, odgovor lists.get). Prejem (prejmi_iz_kroga) samo od posiljatelja v ozjem krogu TE
  naprave, nikoli ne prepise lokalnega ponudnika in ne odklene zapaha. Namizje nima sifriranega usklajevanja
  skrivnosti (secrets.sync), zato geslo ostane na napravi, kjer je vpisano.
"""
from __future__ import annotations

import logging
import os
import ssl
import threading
from typing import Callable, Optional, Tuple

from . import usenet_bralnik, usenet_nntp, usenet_nzb, usenet_ponudnik as up, usenet_rar, usenet_streznik, usenet_tok
from . import viri_sink

_log = logging.getLogger("safeer.usenet")

IME_DATOTEKE = "usenet-ponudnik.json"

#: ValueError jedra ima stalna sporocila brez vrednosti; strani gre samo koda (kljuc besedila).
_NAPAKE_VNOSA = {
    "usenet ponudnik: neveljaven gostitelj": "n_gostitelj",
    "usenet ponudnik: neveljavna vrata": "n_vrata",
    "usenet ponudnik: neveljavno uporabnisko ime": "n_uporabnik",
    "usenet ponudnik: neveljavno geslo": "n_geslo",
    "usenet ponudnik: najvec_povezav mora biti 1-100": "n_povezav",
    "usenet ponudnik: neveljavno ime": "n_ime",
    "usenet ponudnik: brez TLS samo z nevarno_brez_tls=True": "n_brez_tls",
    "usenet ponudnik: brez TLS samo do naslova IP v domacem omrezju": "n_brez_tls_doma",
}
N_VNOS = "n_vnos"
GESLO_ZA_SPREMEMBO = "geslo_za_spremembo"   # streznik, vrata, TLS ali uporabnik brez gesla: to je nov vpis
GLAVNA_NIT = "glavna_nit"
TLS_PREVERBA = "tls_preverba"
NAPAKA = "napaka"
SHRANJENO = "shranjeno"
SHRANJENO_ZACASNO = "shranjeno_zacasno"     # zbirka ni na voljo: geslo samo do zaprtja Safeer OS
POSODOBLJENO = "posodobljeno"
ODSTRANJENO = "odstranjeno"
NI_VPISAN = "ni_vpisan"
IZ_KROGA = "iz_kroga"

#: Kode, ki jih stran pozna (besedila.js); vsaka druga postane NAPAKA - neznan niz ne gre na zaslon.
KODE = frozenset(set(_NAPAKE_VNOSA.values()) | {
    N_VNOS, GESLO_ZA_SPREMEMBO, GLAVNA_NIT, TLS_PREVERBA, NAPAKA, SHRANJENO, SHRANJENO_ZACASNO, POSODOBLJENO,
    ODSTRANJENO, NI_VPISAN, IZ_KROGA,
    up.NI_GESLA, up.BREZ_TLS, up.RACUN_ZAKLENJEN, up.GESLO_ZAVRNJENO, up.NI_PONUDNIKA,
    up.PREVERBA_TECE,
    up.VELJA.lower(), up.NE_VELJA.lower(), up.ZAKLENJEN.lower(), up.NI_ODGOVORA.lower(), up.PREVEC_POVEZAV.lower(),
    up.PREPOGOSTO.lower(), up.V_UPORABI.lower(), up.NEPREVERJEN.lower(),
})
#: Napake pogona ob predvajanju (usenet_nzb, usenet_tok, usenet_rar, usenet_nntp) gredo naprej kot »pogon_<izid>«;
#: izidi so stalni nizi brez message-id in imen datotek, stran jih ne prikaze posamicno.
PREDPONA_POGONA = "pogon_"


def _koda(k: object) -> str:
    k = str(k or "").lower()
    return k if k in KODE else NAPAKA


def _stevilo(v: object) -> object:
    """Vrata in stevilo povezav iz polja strani: niz s stevkami -> int; drugo ostane, da ga jedro zavrne (ValueError
    brez vrednosti). Omejena dolzina: dolg niz ne gre v int()."""
    if isinstance(v, str) and v.strip().isdigit() and len(v.strip()) <= 6:
        return int(v.strip())
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _niz(v: object) -> str:
    return v.strip() if isinstance(v, str) else ""


class Vezava:
    """Most do enega zapisa ponudnika ([pot_nastavitev]). [kontekst]: samo preizkusi (lastna overitelja); jedro ga
    vseeno preveri z nntp.varen_kontekst - CERT_NONE je zavrnjen pred omrezjem."""

    def __init__(self, pot_nastavitev: str, kontekst: Optional[ssl.SSLContext] = None):
        self.pot = str(pot_nastavitev)
        self._kontekst = kontekst
        #: Klic po spremembi ponudnika (os_katalog: znova zapise viri_za_naprave.json za ozji krog). Brez gesla.
        self.ob_spremembi: Optional[Callable[[], None]] = None
        self._zaklep = threading.Lock()
        self._predvajanje = threading.Lock()   # en film naenkrat: zapiranje starega in odpiranje novega skupaj
        self._strezniki: dict = {}              # Streznik -> bazen racuna

    def __repr__(self) -> str:
        return "Vezava(usenet)"  # brez poti: v njej je domaca mapa

    # -------------------------------------------------------------- vmesnik
    def stanje(self) -> dict:
        """Stanje za okno (brez omrezja, brez gesla in uporabnika) in kljuc besedila stanja."""
        s = dict(up.stanje_za_vmesnik(self.pot))
        s.pop("besedilo", None)          # besedilo je v besedila.js v 6 jezikih, iz jedra samo slovensko
        iz_kroga = s["vpisan"] and up.je_iz_kroga(self.pot)
        if not s["vpisan"]:
            kljuc = NI_VPISAN
        elif not s["geslo_shranjeno"] and s["stanje"] == up.NEPREVERJEN:
            kljuc = IZ_KROGA if iz_kroga else up.NI_GESLA
        else:
            kljuc = str(s["stanje"]).lower()
        s["kljuc"] = _koda(kljuc)
        s["iz_kroga"] = bool(iz_kroga)
        return s

    def _odgovor(self, ok: bool, koda: str, **dodatno) -> dict:
        return dict({"ok": ok, "koda": _koda(koda), "stanje": self.stanje()}, **dodatno)

    def _spremenjeno(self) -> None:
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi()
            except Exception as e:  # noqa: BLE001 - zapis za naprave ne sme podreti vpisa
                _log.info("usenet vezava: ob_spremembi (%s)", type(e).__name__)

    def shrani(self, vnos: object, geslo: object) -> dict:
        """»Shrani«. Z geslom: nov vpis (edini odklepa zapah - jedro). Brez gesla: samo ime in stevilo povezav
        (posodobi_nastavitve), sicer bi vmesnik moral znova poslati geslo in s tem tiho odklenil zapah (pregled 77 G1).
        Prazno uporabnisko ime ob shranjenem ponudniku pomeni »isto kot prej«: stran ga nikoli ne dobi nazaj."""
        if not isinstance(vnos, dict):
            return self._odgovor(False, N_VNOS)
        geslo = geslo if isinstance(geslo, str) else ""
        try:
            star = up.preberi_ponudnika(self.pot)
            d = {
                "gostitelj": _niz(vnos.get("gostitelj")) or (star.gostitelj if star else ""),
                "uporabnik": vnos.get("uporabnik") if isinstance(vnos.get("uporabnik"), str) and vnos.get("uporabnik")
                else (star.uporabnik if star else ""),
                "vrata": _stevilo(vnos.get("vrata", up.VRATA)),
                "tls": vnos.get("tls", True),
                "najvec_povezav": _stevilo(vnos.get("najvec_povezav", up.PRIVZETO_POVEZAV)),
                "ime": vnos.get("ime", "") if isinstance(vnos.get("ime", ""), str) else None,
                "nevarno_brez_tls": vnos.get("nevarno_brez_tls", False),
            }
            if d["ime"] is None:
                return self._odgovor(False, "n_ime")
            d["ime"] = d["ime"].strip()
            p = up.Ponudnik.iz_slovarja(d)
            if not geslo:
                if star is None:
                    return self._odgovor(False, "n_geslo")
                racun = lambda x: (x.gostitelj.lower(), x.uporabnik, x.vrata, x.tls, x.nevarno_brez_tls)  # noqa: E731
                if racun(p) != racun(star):
                    return self._odgovor(False, GESLO_ZA_SPREMEMBO)
                up.posodobi_nastavitve(self.pot, ime=p.ime, najvec_povezav=p.najvec_povezav)
                koda = POSODOBLJENO
            else:
                koda = SHRANJENO if up.shrani_ponudnika(p, geslo, self.pot) else SHRANJENO_ZACASNO
        except ValueError as e:
            return self._odgovor(False, _NAPAKE_VNOSA.get(str(e), N_VNOS))
        except up.NapakaPonudnika as e:
            return self._odgovor(False, e.razlog)
        except Exception as e:  # noqa: BLE001 - besedilo izjeme ne gre ne na stran ne v dnevnik
            _log.info("usenet vezava: shrani (%s)", type(e).__name__)
            return self._odgovor(False, NAPAKA)
        self._spremenjeno()
        return self._odgovor(True, koda)

    def preveri(self) -> dict:
        """»Preveri« (samo klik): izid jedra -> koda. Na glavni niti jedro vrze RuntimeError pred zbirko in omrezjem."""
        try:
            izid = up.preveri_shranjenega(self.pot, kontekst=self._kontekst)
        except up.NapakaPonudnika as e:
            return self._odgovor(False, e.razlog)
        except RuntimeError:
            return self._odgovor(False, GLAVNA_NIT)
        except ValueError:
            return self._odgovor(False, TLS_PREVERBA)   # kontekst brez preverbe potrdila (nntp.varen_kontekst)
        except Exception as e:  # noqa: BLE001
            _log.info("usenet vezava: preveri (%s)", type(e).__name__)
            return self._odgovor(False, NAPAKA)
        return self._odgovor(izid == up.VELJA, izid)

    def odstrani(self) -> dict:
        """»Pozabi ponudnika«: najprej ustavi predvajanje (bazen racuna se zapre), nato jedro zbrise zapis, geslo in
        zapah. Usenet izgine iz izbire virov."""
        try:
            # Pregled 118 N1: isti zaklep kot predvajaj - film, ki se ravno pripravlja, se ne registrira po »Pozabi«
            # (prej je tekel naprej s pozabljenim racunom in bazen s poverilnicami je ostal ziv).
            with self._predvajanje:
                self.ustavi_predvajanje()
                up.pozabi_ponudnika(self.pot)
        except Exception as e:  # noqa: BLE001
            _log.info("usenet vezava: odstrani (%s)", type(e).__name__)
            return self._odgovor(False, NAPAKA)
        self._spremenjeno()
        return self._odgovor(True, ODSTRANJENO)

    # -------------------------------------------------------------- predvajanje (lasten pogon)
    def na_voljo(self) -> bool:
        """Lasten pogon pride v postev: ponudnik s TLS, geslo v zbirki ali pomnilniku in brez zapaha ali zavrnitve.
        Brez omrezja; napaka zbirke pomeni ne."""
        try:
            s = up.stanje_za_vmesnik(self.pot)
        except Exception:  # noqa: BLE001
            return False
        return bool(s["vpisan"] and s["tls"] and s["geslo_shranjeno"] and s["stanje"] in (up.VELJA, up.NEPREVERJEN))

    def predvajaj(self, nzb: bytes, ime_izdaje: str = "") -> Tuple[Optional[str], str]:
        """NZB -> (naslov http://127.0.0.1:<vrata>/<zeton>/video.<k>, "") ali (None, koda). Samo z delovne niti:
        priprava bere glave clankov z omrezja."""
        if threading.current_thread() is threading.main_thread():
            return None, GLAVNA_NIT
        with self._predvajanje:
            self.ustavi_predvajanje()      # pred ustvari_bazen: zapiranje starega bi zaprlo tudi novi bazen racuna
            p = up.preberi_ponudnika(self.pot)
            if p is None:
                return None, up.NI_PONUDNIKA
            bazen = None
            try:
                razclenjen = usenet_nzb.razcleni(nzb)
                bazen = up.ustvari_bazen(p, kontekst=self._kontekst)
                vir, _bajtov = usenet_bralnik.pripravi(razclenjen, bazen.telo)
                bralnik = usenet_bralnik.Bralnik(bazen.telo, vir)
            except up.NapakaPonudnika as e:
                return None, e.razlog
            except (usenet_nzb.NapakaNzb, usenet_tok.NapakaToka, usenet_rar.NapakaRar, usenet_nntp.NapakaNntp) as e:
                self._zapri_bazen(bazen)
                return None, PREDPONA_POGONA + str(getattr(e, "izid", "") or NAPAKA)
            except ValueError:
                self._zapri_bazen(bazen)
                return None, TLS_PREVERBA       # kontekst brez preverbe potrdila: zavrnjen pred omrezjem
            except Exception as e:  # noqa: BLE001
                self._zapri_bazen(bazen)
                _log.info("usenet vezava: priprava (%s)", type(e).__name__)
                return None, NAPAKA
            drzalo: list = []
            try:
                s = usenet_streznik.Streznik(bralnik, ime=getattr(vir, "ime", None) or ime_izdaje or None,
                                             ob_koncu=lambda: self._konec(drzalo[0] if drzalo else None))
            except Exception as e:  # noqa: BLE001
                bralnik.zapri()
                self._zapri_bazen(bazen)
                _log.info("usenet vezava: streznik (%s)", type(e).__name__)
                return None, NAPAKA
            drzalo.append(s)
            with self._zaklep:
                self._strezniki[s] = bazen
            return s.url, ""

    def predvaja(self) -> int:
        with self._zaklep:
            return len(self._strezniki)

    def ustavi_predvajanje(self) -> None:
        with self._zaklep:
            tecejo = list(self._strezniki)
        for s in tecejo:
            s.zapri()          # ob_koncu -> _konec zapre bazen

    def _konec(self, s) -> None:
        with self._zaklep:
            bazen = self._strezniki.pop(s, None)
            se_uporablja = bazen is not None and any(b is bazen for b in self._strezniki.values())
        if bazen is not None and not se_uporablja:
            self._zapri_bazen(bazen)

    @staticmethod
    def _zapri_bazen(bazen) -> None:
        if bazen is None:
            return
        try:
            bazen.zapri()      # povezave racuna se sprostijo: »Preveri« spet sme (ni vec V_UPORABI)
        except Exception as e:  # noqa: BLE001
            _log.info("usenet vezava: zapiranje bazena (%s)", type(e).__name__)

    # -------------------------------------------------------------- ozji krog
    def za_krog(self) -> Optional[dict]:
        """Zapis za naprave v ozjem krogu (viri_sink.razdeli_izvoz ga da samo v del »ozji«): brez gesla, izida
        preverbe in zapaha. Ponudnik brez TLS (izjema za domace omrezje TE naprave) in ponudnik, prejet z druge
        naprave, ne gresta naprej."""
        try:
            p = up.preberi_ponudnika(self.pot)
            if p is None or not p.tls or up.je_iz_kroga(self.pot):
                return None
        except Exception:  # noqa: BLE001
            return None
        return viri_sink.cist_usenet({"gostitelj": p.gostitelj, "uporabnik": p.uporabnik, "vrata": p.vrata,
                                      "tls": p.tls, "najvec_povezav": p.najvec_povezav, "ime": p.ime})

    def prejmi_iz_kroga(self, zapis: object, posiljatelj_v_krogu: bool) -> bool:
        """Zapis z druge naprave (odgovor lists.get). [posiljatelj_v_krogu] mora biti dokaz TE naprave
        (core/link_dostop.v_ozjem_krogu), ne izjava posiljatelja. Vrne True, ce je ponudnik zdaj zapisan tukaj."""
        if posiljatelj_v_krogu is not True:
            return False
        c = viri_sink.cist_usenet(zapis)
        if c is None:
            return False
        try:
            p = up.Ponudnik.iz_slovarja(c)
            zapisan = up.shrani_iz_kroga(p, self.pot)
        except (ValueError, OSError) as e:
            _log.info("usenet vezava: prejem iz kroga zavrnjen (%s)", type(e).__name__)
            return False
        return zapisan


# ------------------------------------------------------------------ ena vezava na zapis

_VEZAVE: dict = {}
_VEZAVE_ZAKLEP = threading.Lock()


def za_pot(pot_nastavitev: str) -> Vezava:
    """Ista vezava za most (safeer_os.py) in katalog (os_katalog, Debrid.lastni_usenet): en film naenkrat velja za oba."""
    k = os.path.abspath(str(pot_nastavitev))
    with _VEZAVE_ZAKLEP:
        v = _VEZAVE.get(k)
        if v is None:
            v = _VEZAVE[k] = Vezava(k)
        return v


DEJANJA = ("stanje", "shrani", "preveri", "odstrani")


def most(vezava: Vezava, a: object) -> dict:
    """Klic mostu mediaUsenetPonudnik: [dejanje, ...]. »shrani«: [shrani, vnos, geslo]. Vedno slovar s kodo -
    izjema ne gre ven (safeer_os.py bi njeno besedilo izpisal in vrnil strani)."""
    a = list(a) if isinstance(a, (list, tuple)) else []
    dejanje = a[0] if a and isinstance(a[0], str) else ""
    try:
        if dejanje == "stanje":
            return {"ok": True, "koda": "", "stanje": vezava.stanje()}
        if dejanje == "shrani":
            return vezava.shrani(a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else "")
        if dejanje == "preveri":
            return vezava.preveri()
        if dejanje == "odstrani":
            return vezava.odstrani()
    except Exception as e:  # noqa: BLE001
        _log.info("usenet vezava: most (%s)", type(e).__name__)
        return {"ok": False, "koda": NAPAKA}
    return {"ok": False, "koda": N_VNOS}
