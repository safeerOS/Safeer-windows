"""Premik po poljih programa s krizcem (locen zaslon za televizor).

Na televizorju je naravno, da smerna tipka skoci na naslednji gumb, ne da miska potuje cez zaslon.
Namizni programi tega ne znajo sami, zato to naredimo mi: prek dostopnosti (AT-SPI) preberemo, kje
so v oknu gumbi, polja in povezave, in kazalec postavimo na sredino najblizjega v smeri, ki jo je
uporabnik pritisnil. Program pod kazalcem pokaze, kaj je izbrano (poudarek ob lebdenju), OK ali A
klikne. Kjer program o sebi nic ne pove (igre), vrnemo False - takrat gre smerna tipka kot tipka.

Nic ne spreminjamo in nic ne beremo iz vsebine: samo vloge, stanja in pravokotnike elementov.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import List, Optional, Tuple

#: Kaj je smiselno izbrati s krizcem.
VLOGE = {
    "push button", "button", "toggle button", "check box", "radio button", "menu item",
    "check menu item", "radio menu item", "combo box", "entry", "text", "password text",
    "link", "list item", "page tab", "slider", "spin button", "icon", "tree item", "table cell",
    "menu", "switch",
}
#: Polja za besedilo: OK na njih odpre tipkovnico na televizorju.
VLOGE_BESEDILO = {"entry", "text", "password text"}
#: Kontrole, ki jim kolesce spremeni vrednost ali zavihek: na njih stran ne drsimo.
VLOGE_KOLESCE = {"slider", "spin button", "combo box", "page tab", "scroll bar"}
#: Koren spletne vsebine: kar je pod njim, doloca stran (velikost, polozaj, fokus), ne program.
VLOGE_DOKUMENT = {"document web", "document frame"}
#: Vidno obmocje: vsebina zunaj njega ni vidna. Dokument strani v WebKitu je velik kot vsa stran (izmerjeno
#: 5. 11. 2026: 40700 x 30500 ob elementu z velikansko sirino), vidni del pove njegov stars »scroll pane«.
VLOGE_OBREZ = VLOGE_DOKUMENT | {"scroll pane", "viewport"}
#: Meje, da en pritisk nikoli ne traja dolgo tudi v velikem programu.
NAJVEC_ELEMENTOV = 1500
NAJVEC_GLOBINA = 60
#: Kako dolgo velja prebrani seznam elementov (okno se med brskanjem redko spremeni).
VELJA_S = 8.0


def _atspi():
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        return Atspi
    except Exception:
        return None


# sredina x, y; x, y, sirina, visina (zaslon); ali ima fokus programa (0/1); ali je polje za besedilo (0/1);
# kolesce (0/1); pot v drevesu dostopnosti (indeksi otrok od korena okna); ali je element strani (0/1)
Element = Tuple[float, ...]
#: Rok za preverbo cilja tik pred klikom OK: ce pomocnik ne odgovori, kliknemo kot prej (ne vemo vec kot prej).
ROK_ZADETKA_S = 1.0


def _presek(a, b):
    """Presek pravokotnikov (x0, y0, x1, y1) ali None, ce se ne prekrivata."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _pod_potjo(pot: str, izbrana: str) -> bool:
    """Zadetek je izbrani element ali njegov potomec (besedilo v gumbu)."""
    return izbrana == "" or pot == izbrana or pot.startswith(izbrana + "/")


def izberi(elementi: List[Element], tocka: Tuple[float, float], smer: str) -> Optional[Element]:
    """Najblizji element v smeri. Najprej v stozcu 45 stopinj, sicer kjerkoli na tisti strani."""
    x0, y0 = tocka
    if smer in ("levo", "desno"):
        # Levo in desno ostaneta v isti vrsti: element mora segati cez visino, na kateri smo.
        # Prej je desno na koncu vrstice (zavihki v brskalniku) skocilo v vrsto spodaj -
        # v naslednjo vrsto gre uporabnik s tipko dol, ne sam od sebe.
        elementi = [e for e in elementi if len(e) < 6 or e[3] - 6 <= y0 <= e[3] + e[5] + 6]
    najboljsi, ocena_naj = None, None
    for stozec in (True, False):
        for e in elementi:
            dx, dy = e[0] - x0, e[1] - y0
            if smer == "desno":
                glavna, precna = dx, dy
            elif smer == "levo":
                glavna, precna = -dx, dy
            elif smer == "dol":
                glavna, precna = dy, dx
            elif smer == "gor":
                glavna, precna = -dy, dx
            else:
                return None
            if glavna <= 4:
                continue
            if stozec and abs(precna) > glavna:
                continue
            ocena = glavna + 2.5 * abs(precna)
            if ocena_naj is None or ocena < ocena_naj:
                najboljsi, ocena_naj = e, ocena
        if najboljsi is not None:
            return najboljsi
    return None


class Fokus:
    """Premikanje po poljih okna, ki je v ospredju na drugem zaslonu."""

    def __init__(self, drugi) -> None:
        self.drugi = drugi
        self._kljuc = threading.Lock()
        self._predpomnilnik: Tuple[float, object, List[Element]] = (0.0, None, [])
        #: Kje je kazalec po nasi vednosti (zaslonske koordinate); None = ne vemo.
        self.tocka: Optional[Tuple[float, float]] = None
        #: Element, na katerem je kazalec po zadnjem skoku (za okvir na televizorju); None = nobeden.
        self.izbira: Optional[Element] = None
        #: Zadnji pritisk je naletel na okno, ki o svojih gumbih nic ne pove.
        self.brez_gumbov = False
        #: Zadnji pritisk je bil na robu (v tisti smeri ni vec nicesar vidnega).
        self.na_robu = False
        self._zadnje_okno = None
        #: Zadnji OK ni kliknil: pod kazalcem ni bil vec element, ki ga je kazal okvir (link_zaslon pokaze novo izbiro).
        self.zavrnjen_klik = False

    def ustavi(self) -> None:
        p, self._pomocnik = self._pomocnik, None
        if p is not None:
            try:
                p.kill()
                p.wait(2)
            except Exception:
                pass
        self.pozabi()
        self.tocka = None
        self.izbira = None
        self._zadnje_okno = None

    def osvezi_izbiro(self) -> Optional[Element]:
        """Po kliku: je pod kazalcem se vedno element? Program se je morda spremenil (odprl meni,
        novo okno), zato ga preberemo znova. Tako okvir ostane na gumbu, ki ga uporabnik pritiska
        (kalkulator), in izgine, ce gumba tam ni vec."""
        with self._kljuc:
            t = self.tocka
            okno = self._okno() if t is not None else None
            if okno is None:
                self.izbira = None
                return None
            self._predpomnilnik = (0.0, None, [])
            elementi = self._elementi(okno)
            pod = [e for e in elementi if e[2] <= t[0] <= e[2] + e[4] and e[3] <= t[1] <= e[3] + e[5]]
            self.izbira = min(pod, key=lambda e: e[4] * e[5]) if pod else None
            self._zadnje_okno = okno
            return self.izbira

    def pred_klikom(self) -> bool:
        """Tik pred klikom OK: ali je pod kazalcem se vedno element, ki ga kaze okvir na televizorju?

        Seznam elementov velja do VELJA_S in je bil prebran pred premikom kazalca. Zlonamerna stran ob mouseover
        pod kazalec premakne tuj okvir (iframe) ali prekrivalo - OK bi kliknil cilj, ki ga uporabnik ni izbral,
        okvir pa bi se kazal staro izbiro. Program zato vprasamo, kaj je pod tocko (AT-SPI GetAccessibleAtPoint, v
        brskalniku pravo iskanje zadetka z vrstnim redom plasti). Ce to ni izbrani element ali njegov potomec, ne
        kliknemo: okvir skoci na to, kar je zdaj tam, in drugi OK klikne to - uporabnik vidi, kaj klikne.
        Kazalec, ki ga je premaknil uporabnik sam (miska, dotik: izbira je None), gre naprej kot z misko.
        Element preverimo samo pri vsebini strani (tam doloca postavitev stran); okno pa vedno: novo okno (window.open
        pod kazalcem, pogovorno okno) OK ne klikne na slepo. Programi brez iskanja zadetka (ali ki se ne spustijo v
        spletno vsebino) kliknejo kot doslej - ne vemo vec kot prej, daljinec pa ne sme nehati delati."""
        with self._kljuc:
            self.zavrnjen_klik = False
            e, t = self.izbira, self.tocka
            if e is None or t is None or len(e) < 10:
                return True
            okno = self._okno()
            if okno is not None and okno == self._zadnje_okno:
                if not (len(e) > 10 and e[10]):
                    return True          # element programa (ne strani): postavitve stran ne doloca
                odgovor = self._pomocnik_zahteva({"okno": list(okno), "tocka": [t[0], t[1]]}, ROK_ZADETKA_S)
                if not isinstance(odgovor, dict):
                    return True          # pomocnik ne odgovori: ne vemo vec kot prej, klik kot doslej
                if not odgovor.get("zunaj"):
                    pot = odgovor.get("pot")
                    if pot is None or _pod_potjo(str(pot), str(e[9])):
                        return True      # program ne zna iskati zadetka ali je cilj isti
                    if not odgovor.get("v_strani") and _pod_potjo(str(e[9]), str(pot)):
                        return True      # iskanje se je ustavilo nad spletno vsebino (ne vemo vec kot prej)
            # Drugo okno (pogovorno, novo okno strani), cilj zunaj okna ali drug element: ne kliknemo.
            print("[fokus] OK ni kliknil: cilj pod kazalcem se je spremenil", flush=True)
            self.zavrnjen_klik = True
            self.izbira = None
            if okno is not None:
                self._predpomnilnik = (0.0, None, [])
                elementi = self._elementi(okno)
                pod = [x for x in elementi if x[2] <= t[0] <= x[2] + x[4] and x[3] <= t[1] <= x[3] + x[5]]
                self.izbira = min(pod, key=lambda x: x[4] * x[5]) if pod else None
                self._zadnje_okno = okno
            return False

    def profil(self) -> str:
        """Kaksen program je v ospredju: 'brskalnik' ali prazno (za barvne tipke daljinca)."""
        okno = self._okno()
        if okno is None:
            return ""
        from core.link_sway import _je_spletni_brskalnik
        return "brskalnik" if _je_spletni_brskalnik(okno[0]) else ""

    def brskalnik_na_strani(self) -> bool:
        """V ospredju je brskalnik, ki ne kaze nicesar cez cel zaslon (video): tam Nazaj pomeni
        prejsnjo stran. Cez cel zaslon Nazaj ostane Escape - to video vrne v okno."""
        n = self._v_ospredju()
        if n is None or n.get("fullscreen_mode"):
            return False
        from core.link_sway import _je_spletni_brskalnik
        return _je_spletni_brskalnik(int(n["pid"]))

    def pozabi(self) -> None:
        """Po kliku se okno lahko spremeni: naslednji pritisk prebere elemente znova."""
        self._predpomnilnik = (0.0, None, [])

    # ------------------------------------------------------------------ okno in elementi
    def _okno(self) -> Optional[Tuple[int, int, int, int, int]]:
        """(pid, x, y, sirina, visina) okna v ospredju na drugem zaslonu."""
        n = self._v_ospredju()
        if n is None:
            return None
        r, w = n.get("rect") or {}, n.get("window_rect") or {}
        return (int(n["pid"]), int(r.get("x", 0)) + int(w.get("x", 0)), int(r.get("y", 0)) + int(w.get("y", 0)),
                int(w.get("width", r.get("width", 0))), int(w.get("height", r.get("height", 0))))

    def _v_ospredju(self) -> Optional[dict]:
        """Vozlisce sway okna v ospredju na drugem zaslonu (ali None)."""
        try:
            drevo = json.loads(self.drugi._msg([], "get_tree") or "{}")
        except ValueError:
            return None
        najdeno = []

        def hodi(n):
            if n.get("focused") and n.get("pid"):
                najdeno.append(n)
            for o in n.get("nodes", []) + n.get("floating_nodes", []):
                hodi(o)
        hodi(drevo)
        return najdeno[0] if najdeno else None

    def _elementi(self, okno) -> List[Element]:
        zdaj = time.monotonic()
        cas, kljuc, elementi = self._predpomnilnik
        if kljuc == okno and zdaj - cas < VELJA_S:
            return elementi
        elementi = self._vprasaj_pomocnika(okno)
        self._predpomnilnik = (zdaj, okno, elementi)
        return elementi

    # AT-SPI v procesu Controla (GTK, vec niti) je Control sesul - zato bere locen proces. Ce ta
    # pade ali obvisi, ga ubijemo in naslednjic zazenemo znova; Control ostane ziv.
    _pomocnik: Optional[subprocess.Popen] = None

    @staticmethod
    def _okolje_pomocnika(koren: str) -> dict:
        # Brez DISPLAY: z njim AT-SPI vzame vodilo glavnega namizja (lastnost korena X :0), programi
        # na drugem zaslonu pa so na vodilu seje (org.a11y.Bus) - tam jih je videl samo brez njega.
        o = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        o["PYTHONPATH"] = koren
        return o

    def _vprasaj_pomocnika(self, okno) -> List[Element]:
        odgovor = self._pomocnik_zahteva(list(okno), 4.0)
        if isinstance(odgovor, list):
            return [tuple(e) for e in odgovor]
        return []

    def _pomocnik_zahteva(self, zahteva, rok: float):
        """Ena vrstica JSON pomocniku, odgovor (razclenjen JSON) ali None, ce ne odgovori v roku."""
        for _ in range(2):
            p = self._pomocnik
            if p is None or p.poll() is not None:
                koren = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                try:
                    from core import okolje_procesa
                    p = subprocess.Popen(okolje_procesa.python_ukaz() + ["-m", "core.link_fokus"], cwd=koren,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                         env=self._okolje_pomocnika(koren))
                except Exception:
                    return []
                self._pomocnik = p
            try:
                p.stdin.write(json.dumps(zahteva) + "\n")
                p.stdin.flush()
                from core import os_deskriptorji
                pripravljen = os_deskriptorji.berljivi([p.stdout], rok)     # brez meje 1024 (select)
                vrstica = p.stdout.readline() if pripravljen else ""
                if vrstica:
                    return json.loads(vrstica)
            except Exception:
                pass
            try:
                p.kill()
            except Exception:
                pass
            self._pomocnik = None
        return None

    # ------------------------------------------------------------------ premik
    def premakni(self, smer: str) -> bool:
        """Kazalec na naslednji element v smeri. False, kadar okno o sebi nic ne pove (igra)."""
        with self._kljuc:
            self.na_robu = False
            okno = self._okno()
            if okno is None:
                self.izbira = None
                return False
            elementi = self._elementi(okno)
            if not elementi:
                print("[fokus] okno %s: ni elementov" % (okno,), flush=True)
                self.izbira, self.brez_gumbov = None, True
                return False
            self.brez_gumbov = False
            _, ox, oy, sirina, visina = okno
            t = self.tocka
            novo_okno = okno != self._zadnje_okno
            self._zadnje_okno = okno
            if novo_okno or t is None or not (ox <= t[0] <= ox + sirina and oy <= t[1] <= oy + visina):
                # Prvi pritisk ali novo okno (tudi pogovorno): zacnemo tam, kjer ima fokus program
                # sam (v pogovornem oknu je to navadno privzeti gumb), sicer najblize sredini. Fokus
                # elementa strani (focus() v brskalniku) doloci stran, zato ga tu ne upostevamo.
                fokusirani = [e for e in elementi if len(e) > 6 and e[6] and not (len(e) > 10 and e[10])]
                if fokusirani:
                    cilj = fokusirani[0]
                else:
                    sredina = (ox + sirina / 2.0, oy + visina / 2.0)
                    cilj = min(elementi, key=lambda e: (e[0] - sredina[0]) ** 2 + (e[1] - sredina[1]) ** 2)
            else:
                cilj = izberi(elementi, t, smer)
                if cilj is None:
                    self.na_robu = True  # na robu: ostanemo, kjer smo (ne skocimo drugam)
                    return True
            self.izbira = cilj
            self.tocka = (cilj[0], cilj[1])
            ok = self.drugi.vnos.absolutno(int(cilj[0]), int(cilj[1]))
            if not ok:
                print("[fokus] premik kazalca ni uspel", flush=True)
            return ok

def _zamik_okna(Atspi, okvir, sirina: int, visina: int) -> Optional[Tuple[int, int]]:
    """Kje v koordinatah WINDOW tega okvirja se zacne vidno okno (sirina x visina), ali None, ce
    okvir ni to okno. GTK4 okoli okna na Waylandu risa nevidno senco (20 tock): koordinate
    elementov so merjene od roba sence, sway pa okno postavi brez nje - brez popravka je bil vsak
    okvir in klik zamaknjen navzdol in desno."""
    try:
        e = okvir.get_extents(Atspi.CoordType.WINDOW)
        if abs(e.width - sirina) <= 4 and abs(e.height - visina) <= 4:
            return (max(0, e.x), max(0, e.y))
        for k in range(min(okvir.get_child_count(), 8)):
            c = okvir.get_child_at_index(k)
            if c is None:
                continue
            ce = c.get_extents(Atspi.CoordType.WINDOW)
            if abs(ce.width - sirina) <= 4 and abs(ce.height - visina) <= 4 and ce.x >= 0 and ce.y >= 0:
                return (ce.x, ce.y)
    except Exception:
        pass
    return None


#: Zadnji koren v pomoznem procesu: preverba pred klikom sledi branju elementov istega okna in ji iskanja po
#: namizju ni treba ponavljati (izmerjeno 5. 11. 2026: 15-85 ms od priblizno 70-250 ms preverbe na obremenjenem
#: prenosniku). Velja samo za isto okno (pid in pravokotnik), ki ga je pravkar vrnilo branje elementov.
_zadnji_koren: list = [None, None]


def _koren(Atspi, okno):
    """(koren, dx, dy, globina0) za okno (pid, x, y, sirina, visina) ali None, ce programa ni v AT-SPI."""
    k = _koren_iskanje(Atspi, okno)
    _zadnji_koren[:] = [tuple(okno), k]
    return k


def _koren_iskanje(Atspi, okno):
    pid, _ox, _oy, sirina, visina = okno
    aplikacija = None
    try:
        namizje = Atspi.get_desktop(0)
        for i in range(namizje.get_child_count()):
            a = namizje.get_child_at_index(i)
            try:
                if a is not None and a.get_process_id() == pid:
                    aplikacija = a
                    break
            except Exception:
                continue
    except Exception:
        return None
    if aplikacija is None:
        return None
    # Samo okno, ki je res v ospredju (program ima lahko vec oken: GIMP in njegovo pogovorno okno,
    # dve okni brskalnika). Prej so se elementi vseh oken mesali med seboj.
    kandidati = []
    try:
        for j in range(aplikacija.get_child_count()):
            f = aplikacija.get_child_at_index(j)
            if f is None:
                continue
            st = f.get_state_set()
            if not st.contains(Atspi.StateType.SHOWING):
                continue
            z = _zamik_okna(Atspi, f, sirina, visina)
            if z is not None:
                kandidati.append((0 if st.contains(Atspi.StateType.ACTIVE) else 1, j, f, z))
    except Exception:
        kandidati = []
    if kandidati:
        kandidati.sort(key=lambda k: (k[0], k[1]))
        return kandidati[0][2], kandidati[0][3][0], kandidati[0][3][1], 1
    return aplikacija, 0, 0, 0


def preberi_elemente(okno) -> List[Element]:
    """V pomoznem procesu: elementi okna (pid, x, y, sirina, visina) prek AT-SPI."""
    Atspi = _atspi()
    if Atspi is None:
        return []
    _pid, ox, oy, sirina, visina = okno
    elementi: List[Element] = []
    k = _koren(Atspi, okno)
    if k is None:
        return elementi
    koren, dx, dy, globina0 = k
    pregledanih = [0]

    # Element vzamemo samo z delom, ki je v oknu in (za vsebino strani) v obmocju spletnega pogleda, in kazalec
    # postavimo na sredino TEGA dela. Prej je zadostoval zacetek v oknu: stran je naredila role=button z velikansko
    # sirino ali visino in sredina je padla izven okna ali na orodno vrstico brskalnika (napadalski pregled 5. 11. 2026).
    # Uporabnik zato ne izgubi delno vidnih gumbov - kazalec gre na njihov vidni del.
    def zberi(o, globina, pot, obmocje, v_strani):
        if o is None or globina > NAJVEC_GLOBINA or pregledanih[0] > NAJVEC_ELEMENTOV:
            return
        pregledanih[0] += 1
        try:
            st = o.get_state_set()
            # Aplikacija sama (koren) ni "prikazana"; skrite veje pod njo preskocimo.
            if globina > 0 and not st.contains(Atspi.StateType.SHOWING):
                return
            vloga = o.get_role_name()
            if globina > globina0 and vloga in VLOGE_OBREZ:
                try:
                    d = o.get_extents(Atspi.CoordType.WINDOW)
                except Exception:
                    d = None         # brez pravokotnika ne obrezemo (prej tudi ne)
                if d is not None and d.width > 0 and d.height > 0:
                    obmocje = _presek(obmocje, (d.x - dx, d.y - dy, d.x - dx + d.width, d.y - dy + d.height))
                    if obmocje is None:
                        return       # obmocje ni vidno: nic v njem ni za izbiro
                v_strani = v_strani or vloga in VLOGE_DOKUMENT
            if vloga in VLOGE and st.contains(Atspi.StateType.SENSITIVE) and \
                    (vloga not in ("text",) or st.contains(Atspi.StateType.EDITABLE)):
                e = o.get_extents(Atspi.CoordType.WINDOW)
                ex, ey = e.x - dx, e.y - dy
                vidno = _presek(obmocje, (ex, ey, ex + e.width, ey + e.height))
                if vidno is not None and vidno[2] - vidno[0] > 2 and vidno[3] - vidno[1] > 2:
                    x, y = ox + vidno[0], oy + vidno[1]
                    w, h = vidno[2] - vidno[0], vidno[3] - vidno[1]
                    elementi.append((x + w / 2.0, y + h / 2.0, x, y, w, h,
                                     1 if st.contains(Atspi.StateType.FOCUSED) else 0,
                                     1 if vloga in VLOGE_BESEDILO else 0,
                                     1 if vloga in VLOGE_KOLESCE else 0,
                                     pot, 1 if v_strani else 0))
            for i in range(o.get_child_count()):
                zberi(o.get_child_at_index(i), globina + 1, (pot + "/" if pot else "") + str(i), obmocje, v_strani)
        except Exception:
            return
    zberi(koren, globina0, "", (0, 0, sirina, visina), False)
    return elementi


def zadetek(okno, tocka) -> dict:
    """V pomoznem procesu: kateri element je pod zaslonsko tocko - {"pot": pot od korena okna, "v_strani": ali je
    zadetek spletna vsebina (dokument ali v njem)}, {"pot": None}
    (program iskanja zadetka ne zna ali napaka: ne vemo) ali {"zunaj": True} (zadetek ni v tem oknu).
    GetAccessibleAtPoint vrne otroka pod tocko; spustimo se do najglobljega. V brskalniku je to pravo iskanje
    zadetka (upostevan vrstni red plasti), zato prekrivalo ali premaknjen okvir strani da drugo pot."""
    Atspi = _atspi()
    if Atspi is None:
        return {"pot": None}
    _pid, ox, oy, _s, _v = okno
    k = _zadnji_koren[1] if _zadnji_koren[0] == tuple(okno) and _zadnji_koren[1] is not None else _koren(Atspi, okno)
    if k is None:
        return {"pot": None}
    koren, dx, dy, _g = k
    x, y = int(tocka[0] - ox + dx), int(tocka[1] - oy + dy)
    try:
        if not koren.get_state_set().contains(Atspi.StateType.SHOWING) and _g:
            return {"zunaj": True}       # okno je medtem izginilo
    except Exception:
        return {"pot": None}
    try:
        tren = koren
        for _ in range(NAJVEC_GLOBINA):
            try:
                nasl = tren.get_accessible_at_point(x, y, Atspi.CoordType.WINDOW)
            except Exception:
                nasl = None
            if nasl is None or nasl == tren:
                if tren.get_role_name() in VLOGE_DOKUMENT:
                    break            # v dokumentu velja iskanje zadetka strani; brez zadetka ostane dokument
                # GTK4 se ustavi na svojem vsebniku (izmerjeno 5. 11. 2026: na »panel« nad spletnim pogledom). Do
                # spletne vsebine se spustimo po pravokotnikih otrok (zadnji je narisan zgoraj); od dokumenta naprej
                # odgovarja iskanje zadetka WebKita samo.
                nasl = None
                for i in reversed(range(min(tren.get_child_count(), NAJVEC_ELEMENTOV))):
                    c = tren.get_child_at_index(i)
                    try:
                        ce = c.get_extents(Atspi.CoordType.WINDOW) if c is not None and \
                            c.get_state_set().contains(Atspi.StateType.SHOWING) else None
                    except Exception:
                        ce = None
                    if ce is not None and ce.x <= x < ce.x + ce.width and ce.y <= y < ce.y + ce.height:
                        nasl = c
                        break
                if nasl is None:
                    break
            tren = nasl
        if tren == koren:
            return {"pot": None}
        indeksi, o, v_strani = [], tren, False
        for _ in range(NAJVEC_GLOBINA * 2):
            if o == koren:
                return {"pot": "/".join(reversed(indeksi)), "v_strani": v_strani}
            v_strani = v_strani or o.get_role_name() in VLOGE_DOKUMENT
            nad = o.get_parent()
            if nad is None:
                return {"zunaj": True}
            indeksi.append(str(o.get_index_in_parent()))
            o = nad
    except Exception:
        pass
    return {"pot": None}


def _streznik() -> None:
    """Pomozni proces: ena vrstica JSON (okno) noter, ena vrstica JSON (elementi) ven."""
    for vrstica in sys.stdin:
        try:
            zahteva = json.loads(vrstica)
            if isinstance(zahteva, dict):
                odgovor = zadetek(tuple(zahteva["okno"]), tuple(zahteva["tocka"]))
            else:
                odgovor = preberi_elemente(tuple(zahteva))
        except Exception:
            odgovor = {"pot": None} if vrstica.lstrip().startswith("{") else []
        sys.stdout.write(json.dumps(odgovor) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _streznik()


__all__ = ["Fokus", "izberi", "VLOGE"]
