"""Deljenje prek Huba na racunalniku: besedilo, datoteka in zaslon med napravami.

Isti protokol kot Hub na Androidu (HubHttp.kt, HubTokovi.kt), da odjemalcev ni treba spreminjati:

  * ``POST /cast/share/text`` {target, text}, zeton v glavi  -> cilju ``share.text {text}``;
  * ``PUT  /cast/file?name=&target=&from=``, telo = datoteka, zeton v glavi, neobvezno ``x-safeer-sha256``
    -> datoteka pocaka na Hubu, cilju ``share.file {id, name, size, path, sha256}``;
  * ``GET  /cast/file/<id>?k=<kljuc>`` -> cilj datoteko prevzame (kljuc je iz ``share.file``);
  * ``POST /cast/share/screen/start`` {target}, zeton v glavi -> ``{id, push_path, view_path}``, cilju
    ``share.screen {action: "start", id, path}``;
  * ``POST <push_path>`` brez dolzine telesa: okvirji (4 bajti dolzine, big-endian + JPEG), dokler posiljatelj deli;
  * ``GET  /cast/screen/<id>/view?k=`` stran gledalca, ``.../stream?k=`` tok MJPEG, ``.../state?k=`` ali se tece;
  * ``POST /cast/share/screen/stop`` {id} -> cilju ``share.screen {action: "stop", id}``.

Do te razlicice je racunalnik kot sredisce znal samo posredovati sporocila; teh treh poti ni imel, zato »Poslji
besedilo« in »Poslji datoteko« med napravami nista delala, kadar je bilo sredisce racunalnik (PUT -> 501, POST -> 404).

Pravila (kot HubTokovi): datoteka se pise na disk v koscih in nikoli ne sestavlja v pomnilniku; prostor na disku se
preveri pred sprejemom; neprevzeta datoteka se po eni uri izbrise. Stevila hkratnih prenosov, cakajocih datotek,
deljenih zaslonov in gledalcev ne omejuje stevilka (lastnik, 18. 10. 2026: prej 3 prenosi, 64 datotek, 4 zasloni,
4 gledalci - v podjetju bi sodelavci dobivali »prevec_…«), ampak viri racunalnika (core/link_viri.py): ob pomanjkanju
odgovor 503 s kodo ni_virov, ki jo posiljatelj pokaze (in posiljanje poskusi znova). Posiljatelj
je lastnik zetona - ``from`` iz poizvedbe ne velja nic.

Zaslon (od kroga 109; prej je sredisce racunalnika na te poti odgovorilo 404 in racunalnik racunalniku zaslona ni
mogel pokazati): okvirji gredo iz toka posiljatelja naravnost v kratke vrste gledalcev - nic na disk, nic se ne
kopici. Dodano glede na Android: deljenje se konca tudi, ko ga nihce vec ne gleda, posiljatelj pa razlog konca
dobi v odgovoru na svoj tok. Stran gledalca je samo za gledanje.

Modul ne pozna omrezja: dobi bralni tok in vrne kodo HTTP z odgovorom, zato je preizkusljiv brez vticnikov.
"""

from __future__ import annotations

import collections
import hashlib
import html
import os
import secrets
import shutil
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from core import link_viri

#: Vir za en prenos skozi sredisce (core/link_viri): odprta datoteka in medpomnilniki (KOS 64 KiB, vticnica).
DESKRIPTORJEV_PRENOSA = 1
POMNILNIK_PRENOSA = 1024 * 1024
#: Besedilo napake, kadar sredisce nima virov (posiljatelj ga pokaze po kodi link_viri.KODA v svojem jeziku).
BESEDILO_BREZ_VIROV = "Središče ima zdaj premalo virov (povezav ali pomnilnika). Poskusi znova čez nekaj trenutkov."
#: Prej 4 GB. Datoteka gre na disk v koscih in nikoli v pomnilnik, zato je meja samo prostor na disku (preveri);
#: ta stevilka le zavrne ocitno napacno dolzino (lastnik, 11. 10. 2026: »brez omejitve 4 GB«).
NAJVECJA_DATOTEKA = 1024 ** 4
#: Prekinjena oddaja (izpad Wi-Fi) pocaka toliko casa od zadnjega prejetega kosa; posiljatelj nadaljuje, kjer je ostal.
DELNA_VELJA_S = 3600.0
CAKANJE_DELNE_S = 10.0
NAJVEC_GLOBINA_MAPE = 16
#: Rezerva diska je ista kot drugod v Linku (link_viri.rezerva_diska: 2 % diska, najmanj 1 GiB, najvec 10 GiB; tudi
#: zgodovina Teamworka). Prej fiksnih 200 MiB: na disku 500 GB je oddaja pustila 0,04 % prostega (pregled 19. 10. 2026).
DATOTEKA_VELJA_S = 3600.0
NAJVEC_BESEDILA = 20_000
NAJVEC_IMENA_DATOTEKE = 180
KOS = 64 * 1024


def privzeta_mapa(windows: Optional[bool] = None) -> str:
    """Zacasna mapa za datoteke, ki cakajo na prevzem: predpomnilnik uporabnika, ne /tmp (tam bi jih videli drugi).
    Na Windows mapa programa v profilu uporabnika (kot predpomnilnik pretoka, link_sprotno.mapa_predpomnilnika)."""
    if (os.name == "nt") if windows is None else windows:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS", "deljenje")
    osnova = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(osnova, "safeer-link", "deljenje")


def varno_ime(ime: str) -> str:
    """Samo ime datoteke: brez poti, nadzornih znakov in pik na zacetku (kot varnoIme na Androidu)."""
    ime = str(ime or "").replace("\\", "/").split("/")[-1]
    ime = "".join(z for z in ime if z >= " " and z not in '<>:"|?*\x7f').strip().lstrip(".")
    return ime[:NAJVEC_IMENA_DATOTEKE]


def varna_mapa(mapa: str) -> str:
    """Relativna mapa ob datoteki (posiljanje cele mape): samo varna imena, brez »..«, absolutnih poti in skritih map.
    Prazno = brez mape (kot prej)."""
    deli = [varno_ime(d) for d in str(mapa or "").replace("\\", "/").split("/")]
    deli = [d for d in deli if d and d not in (".", "..")][:NAJVEC_GLOBINA_MAPE]
    return "/".join(deli)[:400]


def napaka(sporocilo: str, koda: str = "") -> dict:
    """Odgovor z napako v obeh oblikah, ki ju odjemalci berejo (napaka/koda in error/error_code)."""
    return {"napaka": sporocilo, "koda": koda, "error": sporocilo, "error_code": koda}


def varno_enako(a, b) -> bool:
    """Primerjava skrivnosti (zeton, kljuc, odtis) v stalnem casu. compare_digest(str, str) za niz z ne-ASCII znakom
    vrze TypeError - kljuc iz poizvedbe ali glave je tako podrl obravnavo zahteve (pregled 19. 10. 2026). Bajti ne."""
    try:
        return secrets.compare_digest(str(a).encode("utf-8", "surrogatepass"), str(b).encode("utf-8", "surrogatepass"))
    except Exception:  # noqa: BLE001 - kar ni mogoce primerjati, ni enako
        return False


class Datoteka:
    def __init__(self, ime: str, velikost: int, pot: str, cilj: str, posiljatelj: str, sha256: str, nastala: float,
                 mapa: str = "") -> None:
        self.id = secrets.token_hex(8)
        self.mapa = mapa
        self.kljuc = secrets.token_hex(16)
        self.ime = ime
        self.velikost = velikost
        self.pot = pot
        self.cilj = cilj
        self.posiljatelj = posiljatelj
        self.sha256 = sha256
        self.nastala = nastala

    def pot_prevzema(self) -> str:
        return "/cast/file/%s?k=%s" % (self.id, self.kljuc)

    def tovor(self) -> dict:
        """Tovor sporocila share.file, kot ga poslje Hub na Androidu."""
        t = {"id": self.id, "name": self.ime, "size": self.velikost, "path": self.pot_prevzema(),
             "sha256": self.sha256, "for_host": False}
        if self.mapa:
            t["dir"] = self.mapa          # starejsi cilj polje prezre in datoteko shrani brez mape
        return t


class Delna:
    """Oddaja, ki se je prekinila: kar je prislo, ostane na disku; odtis tece naprej, posiljatelj nadaljuje od `prejeto`."""

    def __init__(self, kljuc: tuple, ime: str, pot: str, mapa: str, cas: float) -> None:
        self.kljuc = kljuc                # (posiljatelj, cilj, sha256, velikost)
        self.ime = ime
        self.pot = pot
        self.mapa = mapa
        self.prejeto = 0
        self.odtis = hashlib.sha256()
        self.cas = cas
        self.v_teku = False


class Deljenje:
    """Datoteke na poti od posiljatelja do cilja."""

    def __init__(self, mapa: Callable[[], str] = privzeta_mapa, ura: Callable[[], float] = time.time,
                 prosto: Optional[Callable[[str], int]] = None,
                 rezerva: Optional[Callable[[str], int]] = None) -> None:
        self._mapa = mapa
        self.ura = ura
        self._prosto = prosto or (lambda m: shutil.disk_usage(m).free)
        #: Koliko mora ostati prostega po vseh oddajah v teku (link_viri.rezerva_diska).
        self._rezerva = rezerva or link_viri.rezerva_diska
        self._zaklep = threading.Lock()
        self._datoteke: Dict[str, Datoteka] = {}
        self._delne: Dict[tuple, Delna] = {}
        self._prenosov = 0
        #: Bajti, ki jih oddaje v teku se bodo zapisale (zasedeno pod zaklepom, sproscamo sproti z vsakim kosom).
        self._rezervirano = 0
        self._pospravljeno = False

    # ------------------------------------------------------------------ pomozno
    def _pripravi_mapo(self) -> str:
        mapa = self._mapa()
        os.makedirs(mapa, mode=0o700, exist_ok=True)
        if not self._pospravljeno:
            # Ostanki prejsnjega zagona: kljuci zanje so sli s procesom, prevzeti jih ne more nihce vec.
            self._pospravljeno = True
            for ime in os.listdir(mapa):
                try:
                    os.remove(os.path.join(mapa, ime))
                except OSError:
                    pass
        return mapa

    def _zasedi(self) -> bool:
        """Nov prenos (sprejem ali prevzem), ce ima racunalnik vire zanj; stevila prenosov ne omejujemo."""
        razlog = link_viri.preveri(DESKRIPTORJEV_PRENOSA, POMNILNIK_PRENOSA)
        if razlog:
            link_viri.zabelezi(razlog, "prenos")
            return False
        with self._zaklep:
            self._prenosov += 1
            return True

    def _sprosti(self) -> None:
        with self._zaklep:
            self._prenosov = max(0, self._prenosov - 1)

    def stevilo(self) -> int:
        with self._zaklep:
            return len(self._datoteke) + len(self._delne)

    @staticmethod
    def _kljuc(posiljatelj: str, cilj: str, sha256: str, velikost: int) -> tuple:
        return (str(posiljatelj or ""), str(cilj or ""), str(sha256 or "").strip().lower(), int(velikost))

    def odmik(self, posiljatelj: str, cilj: str, sha256: str, velikost: int) -> int:
        """Koliko bajtov prekinjene oddaje te datoteke ze imamo (0 = nic, zacni od zacetka). HEAD /cast/file."""
        self.pocisti()
        with self._zaklep:
            d = self._delne.get(self._kljuc(posiljatelj, cilj, sha256, velikost))
        # Ob izpadu povezave sredisce se nekaj casa bere, kar je ze na poti: posiljatelj, ki vprasa takoj, bi dobil 0
        # in poslal vse znova (izmerjeno 11. 10. 2026 na TV: 302 MB presezka). Pocakamo, da branje konca (do 10 s).
        konec = time.monotonic() + CAKANJE_DELNE_S
        while d is not None and d.v_teku and time.monotonic() < konec:
            time.sleep(0.1)
        return d.prejeto if d is not None and not d.v_teku else 0

    # ------------------------------------------------------------------ sprejem (PUT /cast/file)
    def preveri(self, ime: str, cilj: str, dolzina: int) -> Optional[Tuple[int, dict]]:
        """Napaka, ki jo lahko povemo, se preden beremo telo; None = sprejem se lahko zacne."""
        if not ime or not cilj or dolzina < 0:
            return 400, napaka("Manjka ime, cilj ali dolžina.", "manjka_podatek")
        if dolzina > NAJVECJA_DATOTEKA:
            return 413, napaka("Datoteka je prevelika.", "prevelika")
        self.pocisti()
        try:
            mapa = self._pripravi_mapo()
            prosto = int(self._prosto(mapa))
            rezerva = int(self._rezerva(mapa))
        except OSError:
            return 507, napaka("Datoteke ni mogoče shraniti.", "ni_prostora")
        with self._zaklep:
            zasedeno = self._rezervirano
        if prosto - zasedeno < dolzina + rezerva:
            return 507, napaka("Ni dovolj prostora.", "ni_prostora")
        return None

    def _rezerviraj(self, koliko: int) -> bool:
        """Prostor za `koliko` bajtov: preverjen in zaseden pod istim zaklepom. Prej je vsaka vzporedna oddaja zase
        videla isti prosti prostor in skupaj so disk napolnile do nic; nadaljevanje ga sploh ni preverilo (pregled
        19. 10. 2026). Rezerva diska (link_viri.rezerva_diska) ostane prosta vedno."""
        try:
            mapa = self._pripravi_mapo()
            rezerva = int(self._rezerva(mapa))
        except OSError:
            return False
        with self._zaklep:
            try:
                prosto = int(self._prosto(mapa))
            except OSError:
                return False
            if prosto - self._rezervirano < max(0, koliko) + rezerva:
                return False
            self._rezervirano += max(0, koliko)
            return True

    def _vrni_rezervacijo(self, koliko: int) -> None:
        if koliko > 0:
            with self._zaklep:
                self._rezervirano = max(0, self._rezervirano - koliko)

    def sprejmi(self, vhod, dolzina: int, ime: str, cilj: str, posiljatelj: str,
                napovedan_sha: str = "", skupaj: Optional[int] = None, odmik: int = 0,
                mapa: str = "") -> Tuple[int, dict, Optional[Datoteka]]:
        """Prebere natanko `dolzina` bajtov iz `vhod` v zacasno datoteko. Vrne (koda HTTP, odgovor, datoteka ali None).

        Nadaljevanje (od kroga s prenosom po koscih): `skupaj` je velikost cele datoteke, `odmik` mesto, od koder
        posiljatelj nadaljuje (vprasal je s HEAD). Z napovedanim odtisom se prekinjena oddaja ne zavrze: kar je prislo,
        pocaka DELNA_VELJA_S; odgovor pove `odmik`. Brez `skupaj` je vse kot prej (ena oddaja, cela datoteka)."""
        ime = varno_ime(ime)
        mapa = varna_mapa(mapa)
        # Samo posiljatelj, ki nadaljevanje zna (poslal je x-safeer-size), dobi ohranjen ostanek; starejsi kot prej.
        nadaljevanje = skupaj is not None
        skupaj = dolzina if skupaj is None else int(skupaj)
        odmik = max(0, int(odmik or 0))
        napovedan = (napovedan_sha or "").strip().lower()
        if odmik + dolzina != skupaj and dolzina >= 0:
            return 400, napaka("Dolžina se ne ujema z velikostjo datoteke.", "napacna_dolzina"), None
        if odmik and not napovedan:
            return 400, napaka("Nadaljevanje brez odtisa ni mogoče.", "manjka_odtis"), None
        # Tudi nadaljevanje: prej je preverjanje preskocilo in zapisalo preostanek ne glede na prostor.
        zavrnjeno = self.preveri(ime, cilj, dolzina)
        if zavrnjeno is None and skupaj > NAJVECJA_DATOTEKA:
            zavrnjeno = 413, napaka("Datoteka je prevelika.", "prevelika")
        if zavrnjeno is not None:
            return zavrnjeno[0], zavrnjeno[1], None
        kljuc = self._kljuc(posiljatelj, cilj, napovedan, skupaj) if napovedan and nadaljevanje else None
        with self._zaklep:
            delna = self._delne.get(kljuc) if kljuc else None
            if odmik and (delna is None or delna.v_teku or delna.prejeto != odmik):
                imamo = 0 if delna is None or delna.v_teku else delna.prejeto
                return 409, dict(napaka("Nadaljevanje se ne ujema s tem, kar ima središče.", "napacen_odmik"),
                                 odmik=imamo), None
            if delna is not None and delna.v_teku:
                return 409, dict(napaka("Ta datoteka se že sprejema.", "ze_v_teku"), odmik=0), None
            if delna is not None and not odmik:
                # Posiljatelj zacenja znova (ni vprasal ali ne zna nadaljevati): stari ostanek odpade.
                self._delne.pop(kljuc, None)
                self._odstrani_pot(delna.pot)
                delna = None
            if delna is not None:
                delna.v_teku = True
        if not self._zasedi():
            if delna is not None:
                delna.v_teku = False
            return 503, napaka(BESEDILO_BREZ_VIROV, link_viri.KODA), None
        if not self._rezerviraj(dolzina):
            self._sprosti()
            if delna is not None:
                delna.v_teku = False
            return 507, napaka("Ni dovolj prostora.", "ni_prostora"), None
        rezervirano = dolzina
        if delna is None:
            pot = os.path.join(self._pripravi_mapo(), secrets.token_hex(6) + "-" + ime)
            try:
                os.close(os.open(pot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            except OSError:
                self._sprosti()
                self._vrni_rezervacijo(rezervirano)
                return 507, napaka("Datoteke ni mogoče shraniti.", "ni_prostora"), None
            delna = Delna(kljuc or ("", "", secrets.token_hex(4), skupaj), ime, pot, mapa, self.ura())
            delna.v_teku = True
            if kljuc:
                with self._zaklep:
                    self._delne[kljuc] = delna
        prekinjeno = False
        try:
            with open(delna.pot, "r+b") as izhod:
                izhod.seek(delna.prejeto)
                izhod.truncate()
                konec = delna.prejeto + dolzina
                while delna.prejeto < konec:
                    kos = vhod.read(min(KOS, konec - delna.prejeto))
                    if not kos:
                        break
                    izhod.write(kos)
                    delna.odtis.update(kos)
                    delna.prejeto += len(kos)
                    delna.cas = self.ura()
                    # Zapisano je ze na disku (prosti prostor ga ze steje): rezervacija se zmanjsa sproti.
                    rezervirano -= len(kos)
                    self._vrni_rezervacijo(len(kos))
        except Exception:  # noqa: BLE001 - prekinjena povezava ali poln disk
            prekinjeno = True
        finally:
            self._sprosti()
            self._vrni_rezervacijo(rezervirano)
        if prekinjeno or delna.prejeto != skupaj:
            if kljuc and delna.prejeto < skupaj:
                # Kar je prislo, obdrzimo: odtis je do tod pravilen (izhod je zapisan pred posodobitvijo odtisa).
                delna.v_teku = False
                if prekinjeno:
                    return 500, dict(napaka("Prenos je bil prekinjen.", "prenos_prekinjen"), odmik=delna.prejeto), None
                return 400, dict(napaka("Datoteka ni prišla cela.", "ni_cela"), odmik=delna.prejeto), None
            self._pozabi_delno(delna)
            if prekinjeno:
                return 500, napaka("Prenos je bil prekinjen.", "prenos_prekinjen"), None
            return 400, napaka("Datoteka ni prišla cela.", "ni_cela"), None
        sha256 = delna.odtis.hexdigest()
        if napovedan and napovedan != sha256:
            self._pozabi_delno(delna)
            return 400, napaka("Prstni odtis se ne ujema.", "napacen_odtis"), None
        with self._zaklep:
            if kljuc:
                self._delne.pop(kljuc, None)
            d = Datoteka(ime, skupaj, delna.pot, cilj, posiljatelj, sha256, self.ura(), mapa=delna.mapa or mapa)
            self._datoteke[d.id] = d
        return 200, {"id": d.id, "name": d.ime, "size": skupaj, "key": d.kljuc, "for_host": False, "sha256": sha256}, d

    def _pozabi_delno(self, delna: Delna) -> None:
        with self._zaklep:
            if self._delne.get(delna.kljuc) is delna:
                self._delne.pop(delna.kljuc, None)
        self._odstrani_pot(delna.pot)

    # ------------------------------------------------------------------ prevzem (GET /cast/file/<id>?k=)
    def najdi(self, id_: str, kljuc: str) -> Optional[Datoteka]:
        with self._zaklep:
            d = self._datoteke.get(str(id_ or ""))
        if d is None or not kljuc or not varno_enako(d.kljuc, kljuc) or not os.path.isfile(d.pot):
            return None
        return d

    def zacni_prevzem(self) -> bool:
        return self._zasedi()

    def koncaj_prevzem(self, d: Datoteka, cela: bool) -> None:
        """Po prevzemu je zacasna datoteka opravila svoje; prekinjen prevzem jo pusti (cilj poskusi znova)."""
        self._sprosti()
        if cela:
            self.odstrani(d.id)

    def odstrani(self, id_: str) -> None:
        with self._zaklep:
            d = self._datoteke.pop(id_, None)
        if d is not None:
            self._odstrani_pot(d.pot)

    @staticmethod
    def _odstrani_pot(pot: str) -> None:
        try:
            os.remove(pot)
        except OSError:
            pass

    def pocisti(self) -> None:
        """Datoteke, ki jih v eni uri ni nihce prevzel, izbrisemo."""
        meja = self.ura() - DATOTEKA_VELJA_S
        meja_delnih = self.ura() - DELNA_VELJA_S
        with self._zaklep:
            stare = [i for i, d in self._datoteke.items() if d.nastala < meja]
            stare_delne = [d for d in self._delne.values() if not d.v_teku and d.cas < meja_delnih]
        for i in stare:
            self.odstrani(i)
        for d in stare_delne:
            self._pozabi_delno(d)

    def izprazni(self) -> None:
        """Ob ustavitvi Huba: nic ne ostane na disku."""
        with self._zaklep:
            vse = list(self._datoteke)
            delne = list(self._delne.values())
        for i in vse:
            self.odstrani(i)
        for d in delne:
            self._pozabi_delno(d)


# ---------------------------------------------------------------------- zaslon

#: Vrsta okvirjev enega gledalca: kdor ne dohaja, izgubi starejse okvirje, ne pomnilnika sredisca.
VRSTA_GLEDALCA = 2
NAJVECJI_OKVIR = 2 * 1024 * 1024
#: Deljenih zaslonov in gledalcev ne omejuje stevilka (prej 4 in 4), ampak pomnilnik (core/link_viri): deljenje drzi
#: zadnji okvir in tistega na poti, gledalec svojo vrsto okvirjev; vsak ima eno povezavo (deskriptor).
POMNILNIK_ZASLONA = 2 * NAJVECJI_OKVIR
POMNILNIK_GLEDALCA = VRSTA_GLEDALCA * NAJVECJI_OKVIR
#: Posiljatelj nespremenjen okvir ponovi vsake 4 s (link_deljenje.UTRIP_S); toliko casa brez okvirja pomeni, da je odsel.
BREZ_OKVIRJA_S = 20.0
#: Toliko casa ima posiljatelj po zacetku, da odpre tok okvirjev; sicer deljenje koncamo, da cilj ne ostane zaseden.
ROK_ZA_TOK_S = 20.0
#: Ko odide zadnji gledalec, pocakamo toliko (stran gledalca se lahko nalozi znova), nato deljenje koncamo.
BREZ_GLEDALCEV_S = 10.0
MEJA_TOKA = "safeerokvir"
KONEC_TOKA = ("--%s--\r\n" % MEJA_TOKA).encode("ascii")

#: Zakaj se je deljenje koncalo. Posiljatelj razlog dobi v odgovoru na tok okvirjev in po njem ve, da povezava ni padla.
KONEC_POSILJATELJ = "posiljatelj"            # nehal je posiljati (ali je odsel)
KONEC_USTAVLJENO = "ustavljeno"              # izrecen POST /cast/share/screen/stop
KONEC_BREZ_GLEDALCEV = "ni_gledalcev"        # cilj je gledalca zaprl
KONEC_NI_TOKA = "ni_toka"                    # posiljatelj toka okvirjev ni odprl
KONEC_SREDISCE = "sredisce_se_ustavlja"


def _casovnik(cez_s: float, klic: Callable[[], None]) -> None:
    nit = threading.Timer(cez_s, klic)
    nit.daemon = True
    nit.start()


class Gledalec:
    """En gledalec deljenega zaslona: kratka vrsta okvirjev, iz katere bere njegova zahteva HTTP."""

    def __init__(self) -> None:
        self._vrsta: collections.deque = collections.deque(maxlen=VRSTA_GLEDALCA)
        self._pogoj = threading.Condition()
        self.konec = False

    def ponudi(self, okvir: bytes) -> None:
        with self._pogoj:
            self._vrsta.append(okvir)        # polna vrsta izgubi najstarejsi okvir; nikoli ne cakamo
            self._pogoj.notify()

    def naslednji(self, cakaj_s: float = 1.0) -> Optional[bytes]:
        """Naslednji okvir ali None, ce ga v `cakaj_s` ni (klicatelj takrat preveri, ali deljenje se tece)."""
        with self._pogoj:
            if not self._vrsta and not self.konec:
                self._pogoj.wait(cakaj_s)
            return self._vrsta.popleft() if self._vrsta else None

    def koncaj(self) -> None:
        with self._pogoj:
            self.konec = True
            self._pogoj.notify_all()


class Zaslon:
    """Eno deljenje zaslona: posiljatelj potiska okvirje, gledalci (ciljna naprava) jih berejo."""

    def __init__(self, posiljatelj: str, cilj: str, nastal: float, ime_posiljatelja: str = "") -> None:
        self.id = secrets.token_hex(8)
        self.kljuc = secrets.token_hex(16)
        self.posiljatelj = posiljatelj
        #: Ime za naslov strani gledalca (cigav zaslon je to).
        self.ime_posiljatelja = ime_posiljatelja
        self.cilj = cilj
        self.nastal = nastal
        self.tece = True
        self.razlog = ""
        self.zadnji: Optional[bytes] = None
        self.okvirjev = 0
        self.gledalci: list = []
        #: Posiljatelj je odprl tok okvirjev (samo en tok na deljenje).
        self.ima_tok = False
        #: Kdaj je odsel zadnji gledalec (0 = gledalec je tu ali ga se ni bilo).
        self.brez_gledalcev_od = 0.0

    def pot_potiskanja(self) -> str:
        return "/cast/screen/%s?k=%s" % (self.id, self.kljuc)

    def pot_gledanja(self) -> str:
        return "/cast/screen/%s/view?k=%s" % (self.id, self.kljuc)

    def pot_toka(self) -> str:
        return "/cast/screen/%s/stream?k=%s" % (self.id, self.kljuc)

    def pot_stanja(self) -> str:
        return "/cast/screen/%s/state?k=%s" % (self.id, self.kljuc)

    def tovor_zacetka(self) -> dict:
        """Tovor sporocila share.screen ob zacetku, kot ga poslje sredisce na Androidu."""
        return {"action": "start", "id": self.id, "path": self.pot_gledanja()}

    def tovor_konca(self) -> dict:
        return {"action": "stop", "id": self.id}


class Zasloni:
    """Deljeni zasloni, ki tecejo prek tega sredisca. Brez omrezja: bere iz podane funkcije in polni vrste gledalcev.

    Pravila (kot HubTokovi na Androidu, dodano je zadnje): en deljen zaslon na posiljatelja; z eno napravo deli
    naenkrat ena naprava; omejeno stevilo zaslonov in gledalcev; gledalec, ki ne dohaja, izgubi okvirje; deljenje se
    konca, ko posiljatelj neha, ko ga kdo izrecno ustavi ali ko ga nihce vec ne gleda."""

    def __init__(self, ura: Callable[[], float] = time.time,
                 casovnik: Callable[[float, Callable[[], None]], None] = _casovnik) -> None:
        self.ura = ura
        self._casovnik = casovnik
        self._zaklep = threading.Lock()
        self._zasloni: Dict[str, Zaslon] = {}
        #: Klice se enkrat ob koncu vsakega deljenja (sredisce cilju poslje share.screen stop).
        self.ob_koncu: Optional[Callable[[Zaslon], None]] = None

    def stevilo(self) -> int:
        with self._zaklep:
            return len(self._zasloni)

    def zacni(self, posiljatelj: str, cilj: str, ime_posiljatelja: str = "") -> Tuple[Optional[Zaslon], str, str]:
        """(zaslon, "", "") ali (None, koda, kdo): "naprava_zasedena" (kdo = naprava, ki s ciljem deli) ali
        link_viri.KODA (racunalniku zmanjkuje virov)."""
        with self._zaklep:
            prejsnji = [z.id for z in self._zasloni.values() if z.posiljatelj == posiljatelj]
        for id_ in prejsnji:
            self.koncaj(id_, KONEC_POSILJATELJ)          # nov zacetek istega posiljatelja konca prejsnjega
        with self._zaklep:
            for z in self._zasloni.values():
                if z.cilj == cilj:
                    return None, "naprava_zasedena", z.posiljatelj
            razlog = link_viri.preveri(1, POMNILNIK_ZASLONA)
            if razlog:
                link_viri.zabelezi(razlog, "zaslon")
                return None, link_viri.KODA, ""
            z = Zaslon(posiljatelj, cilj, self.ura(), ime_posiljatelja)
            self._zasloni[z.id] = z
        self._casovnik(ROK_ZA_TOK_S, lambda: self._preveri_tok(z.id))
        return z, "", ""

    def _preveri_tok(self, id_: str) -> None:
        with self._zaklep:
            z = self._zasloni.get(id_)
            if z is None or z.ima_tok:
                return
        self.koncaj(id_, KONEC_NI_TOKA)

    def koncaj(self, id_: str, razlog: str = KONEC_USTAVLJENO) -> Optional[Zaslon]:
        """Konca deljenje (prvi razlog velja); vrne ga ali None, ce ga ni vec."""
        with self._zaklep:
            z = self._zasloni.pop(str(id_ or ""), None)
            if z is None:
                return None
            z.tece = False
            z.razlog = razlog
            gledalci = list(z.gledalci)
        for g in gledalci:
            g.koncaj()
        klic = self.ob_koncu
        if klic is not None:
            try:
                klic(z)
            except Exception:  # noqa: BLE001 - obvestilo cilju ne sme ustaviti konca deljenja
                pass
        return z

    def koncaj_vse(self, razlog: str = KONEC_SREDISCE) -> None:
        with self._zaklep:
            vsi = list(self._zasloni)
        for id_ in vsi:
            self.koncaj(id_, razlog)

    def najdi(self, id_: str, kljuc: str) -> Optional[Zaslon]:
        with self._zaklep:
            z = self._zasloni.get(str(id_ or ""))
        if z is None or not kljuc or not varno_enako(z.kljuc, kljuc):
            return None
        return z

    def po_idju(self, id_: str) -> Optional[Zaslon]:
        with self._zaklep:
            return self._zasloni.get(str(id_ or ""))

    # ------------------------------------------------------------------ posiljatelj (POST /cast/screen/<id>?k=)
    def sprejmi(self, z: Zaslon, beri: Callable[[int], bytes]) -> int:
        """Bere okvirje (4 bajti dolzine, big-endian + JPEG), dokler posiljatelj deli; na koncu deljenje konca.
        `beri(n)` vrne natanko n bajtov, manj ob koncu toka, ali sprozi izjemo (molk, prekinjena povezava).
        Vrne stevilo okvirjev ali -1, ce to deljenje tok ze ima."""
        with self._zaklep:
            if z.ima_tok:
                return -1
            z.ima_tok = True
        try:
            while z.tece:
                glava = beri(4)
                if len(glava) < 4:
                    break
                dolzina = int.from_bytes(glava, "big")
                if dolzina <= 0 or dolzina > NAJVECJI_OKVIR:
                    break
                okvir = beri(dolzina)
                if len(okvir) < dolzina:
                    break
                with self._zaklep:
                    z.zadnji = okvir
                    z.okvirjev += 1
                    gledalci = list(z.gledalci)
                for g in gledalci:
                    g.ponudi(okvir)
        except Exception:  # noqa: BLE001 - posiljatelj je odsel ali molci predolgo
            pass
        finally:
            self.koncaj(z.id, KONEC_POSILJATELJ)
        return z.okvirjev

    # ------------------------------------------------------------------ gledalec (GET /cast/screen/<id>/stream?k=)
    def dodaj_gledalca(self, z: Zaslon) -> Tuple[Optional[Gledalec], str]:
        """(gledalec, "") ali (None, koda): "ni_zaslona" (deljenje je koncano) ali link_viri.KODA (ni virov)."""
        razlog = link_viri.preveri(1, POMNILNIK_GLEDALCA)
        with self._zaklep:
            if not z.tece:
                return None, "ni_zaslona"
            if razlog:
                link_viri.zabelezi(razlog, "gledalec")
                return None, link_viri.KODA
            g = Gledalec()
            z.gledalci.append(g)
            z.brez_gledalcev_od = 0.0
            zadnji = z.zadnji
        if zadnji is not None:
            g.ponudi(zadnji)                 # nov gledalec takoj vidi zadnjo sliko
        return g, ""

    def odstrani_gledalca(self, z: Zaslon, g: Gledalec) -> None:
        with self._zaklep:
            if g in z.gledalci:
                z.gledalci.remove(g)
            if not z.tece or z.gledalci:
                return
            z.brez_gledalcev_od = oznaka = self.ura()
        self._casovnik(BREZ_GLEDALCEV_S, lambda: self._preveri_gledalce(z.id, oznaka))

    def _preveri_gledalce(self, id_: str, oznaka: float) -> None:
        with self._zaklep:
            z = self._zasloni.get(id_)
            if z is None or z.gledalci or z.brez_gledalcev_od != oznaka:
                return
        self.koncaj(id_, KONEC_BREZ_GLEDALCEV)


def del_toka(okvir: bytes) -> bytes:
    """En okvir v toku MJPEG (multipart/x-mixed-replace)."""
    return (("--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % (MEJA_TOKA, len(okvir))).encode("ascii")
            + okvir + b"\r\n")


def stran_gledalca(z: Zaslon) -> str:
    """Stran gledalca: crno ozadje, slika v razmerju. Samo gledanje - tujega racunalnika se od tu ne upravlja
    (za to je »Dostop do tega računalnika« s svojimi pravicami)."""
    naslov = "Safeer Link – zaslon" + ((": " + z.ime_posiljatelja) if z.ime_posiljatelja else "")
    return (_STRAN_GLEDALCA.replace("%%NASLOV%%", html.escape(naslov))
            .replace("%%TOK%%", z.pot_toka()).replace("%%STANJE%%", z.pot_stanja()))


_STRAN_GLEDALCA = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>%%NASLOV%%</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000;-webkit-user-select:none;user-select:none}
#konec{display:none;position:absolute;inset:0;color:#cbd5e1;font:20px sans-serif;align-items:center;justify-content:center;text-align:center;padding:24px}
</style></head><body>
<img id="zaslon" src="%%TOK%%" alt="" draggable="false">
<div id="konec"></div>
<script>
var s=document.getElementById('zaslon'),k=document.getElementById('konec'),koncano=false;
k.textContent=(navigator.language||'').toLowerCase().indexOf('sl')===0?'Deljenje zaslona je končano.':'Screen sharing has ended.';
function konec(){if(koncano)return;koncano=true;s.removeAttribute('src');s.style.display='none';k.style.display='flex';}
s.onerror=konec;
// Tok MJPEG se ob koncu samo ustavi in zadnja slika ostane: sredisce vprasamo, ali deljenje se tece.
setInterval(function(){if(koncano)return;fetch('%%STANJE%%',{cache:'no-store'}).then(function(o){if(o.status===404)konec();}).catch(function(){});},3000);
</script></body></html>"""

STRAN_KONEC = """<!doctype html><html><head><meta charset="utf-8"><title>Safeer Link</title>
<style>html,body{margin:0;height:100%;background:#000;color:#cbd5e1;font:20px sans-serif;display:flex;align-items:center;justify-content:center}</style>
</head><body><div id="konec"></div><script>
document.getElementById('konec').textContent=(navigator.language||'').toLowerCase().indexOf('sl')===0?'Deljenje zaslona je končano.':'Screen sharing has ended.';
</script></body></html>"""
