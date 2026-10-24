"""Peskovnik WebKita (bubblewrap) na Ubuntu 24.04+, ki nepooblascenim programom omeji uporabniske imenske prostore.

WebKitGTK zazene vsak spletni in omrezni proces v peskovniku bubblewrap (/usr/bin/bwrap), ta pa potrebuje uporabniski
imenski prostor. Ubuntu od 24.04 (kernel.apparmor_restrict_unprivileged_userns=1) ga dovoli samo programom s profilom
AppArmor, ki ima pravilo `userns` - tako Ubuntu sam resi epiphany, geary in evolution (paket apparmor 4.0.1, preverjeno
18. 10. 2026). Linux Mint omejitev izklopi (/etc/sysctl.d/20-apparmor-mint.conf), zato se tam to ne zgodi.

Brez dovoljenja bwrap konca z »setting up uid map: Permission denied«, WebKit pa ob tem ne dobi PID spletnega procesa
in konca CEL program z g_error (»Failed to read pid from child process«, SIGTRAP) - Safeer OS bi padal ob vsaki strani.

Resitev v paketu .deb: profili packaging/apparmor/* za nase zaganjalnike (/usr/bin/safeer-os, safeer-control, safeer),
postinst jih nalozi. Otroci (python3, bwrap) ostanejo v profilu, ker zanje ni svojega profila. Kjer profil ne velja
(AppImage, zagon mimo zaganjalnika, nalaganje ni uspelo), pripravi() to zazna s poskusom bwrap - kot WebKit sam v
vsebniku (Source/WTF/wtf/glib/Sandbox.cpp: »Bubblewrap does not work inside of this container, sandboxing will be
disabled«) - in WebKitov peskovnik izklopi, namesto da bi program padel; uporabnik enkrat dobi pojasnilo s popravkom.
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, MutableMapping, Optional

OMEJITEV = "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
OZNAKE = ("/proc/self/attr/apparmor/current", "/proc/self/attr/current")
BWRAP = "/usr/bin/bwrap"
#: Profili v paketih .deb (ime profila = ime datoteke v /etc/apparmor.d).
NASI_PROFILI = ("safeer-os", "safeer-control", "safeer-browser")
IZKLOP = "WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"
#: Isti poskus kot WebKit (isInsideUnsupportedContainer): ce ta ne uspe, spletni proces v peskovniku ne zazivi.
POSKUS = ("--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev", "--unshare-all", "true")

BESEDILA: Dict[str, Dict[str, str]] = {
    "sl": {"naslov": "Spletne strani tečejo brez peskovnika",
           "besedilo": "Ta sistem (Ubuntu) omejuje uporabniške imenske prostore, zato peskovnik spletnih strani ne deluje. "
                       "{program} zato strani odpira brez peskovnika. Popravek (enkrat, z geslom skrbnika): "
                       "sudo apparmor_parser -r /etc/apparmor.d/{profil} — nato {program} znova zaženite.",
           "brez_profila": "Ta sistem (Ubuntu) omejuje uporabniške imenske prostore, zato peskovnik spletnih strani ne deluje. "
                           "{program} zato strani odpira brez peskovnika. Za peskovnik namestite Safeer iz paketa .deb ali kot Flatpak."},
    "en": {"naslov": "Web pages are running without a sandbox",
           "besedilo": "This system (Ubuntu) restricts user namespaces, so the web page sandbox does not work. "
                       "{program} therefore opens pages without the sandbox. Fix (once, with the administrator password): "
                       "sudo apparmor_parser -r /etc/apparmor.d/{profil} — then restart {program}.",
           "brez_profila": "This system (Ubuntu) restricts user namespaces, so the web page sandbox does not work. "
                           "{program} therefore opens pages without the sandbox. For the sandbox, install Safeer from the .deb package or as a Flatpak."},
    "de": {"naslov": "Webseiten laufen ohne Sandbox",
           "besedilo": "Dieses System (Ubuntu) schränkt Benutzer-Namensräume ein, daher funktioniert die Sandbox für "
                       "Webseiten nicht. {program} öffnet Seiten deshalb ohne Sandbox. Behebung (einmalig, mit dem "
                       "Administratorpasswort): sudo apparmor_parser -r /etc/apparmor.d/{profil} — danach {program} neu starten.",
           "brez_profila": "Dieses System (Ubuntu) schränkt Benutzer-Namensräume ein, daher funktioniert die Sandbox für Webseiten nicht. "
                           "{program} öffnet Seiten deshalb ohne Sandbox. Für die Sandbox installieren Sie Safeer als .deb-Paket oder als Flatpak."},
    "es": {"naslov": "Las páginas web se ejecutan sin aislamiento",
           "besedilo": "Este sistema (Ubuntu) restringe los espacios de nombres de usuario, por eso el aislamiento de las "
                       "páginas web no funciona. {program} abre las páginas sin aislamiento. Solución (una vez, con la "
                       "contraseña de administrador): sudo apparmor_parser -r /etc/apparmor.d/{profil} — luego reinicia {program}.",
           "brez_profila": "Este sistema (Ubuntu) restringe los espacios de nombres de usuario, por eso el aislamiento de las páginas web no funciona. "
                           "{program} abre las páginas sin aislamiento. Para el aislamiento, instala Safeer desde el paquete .deb o como Flatpak."},
    "fr": {"naslov": "Les pages web s'exécutent sans bac à sable",
           "besedilo": "Ce système (Ubuntu) restreint les espaces de noms utilisateur, le bac à sable des pages web ne "
                       "fonctionne donc pas. {program} ouvre les pages sans bac à sable. Correction (une fois, avec le mot "
                       "de passe administrateur) : sudo apparmor_parser -r /etc/apparmor.d/{profil} — puis redémarrez {program}.",
           "brez_profila": "Ce système (Ubuntu) restreint les espaces de noms utilisateur, le bac à sable des pages web ne fonctionne donc pas. "
                           "{program} ouvre les pages sans bac à sable. Pour le bac à sable, installez Safeer depuis le paquet .deb ou en Flatpak."},
    "it": {"naslov": "Le pagine web funzionano senza sandbox",
           "besedilo": "Questo sistema (Ubuntu) limita gli spazi dei nomi utente, quindi la sandbox delle pagine web non "
                       "funziona. {program} apre le pagine senza sandbox. Correzione (una volta, con la password di "
                       "amministratore): sudo apparmor_parser -r /etc/apparmor.d/{profil} — poi riavvia {program}.",
           "brez_profila": "Questo sistema (Ubuntu) limita gli spazi dei nomi utente, quindi la sandbox delle pagine web non funziona. "
                           "{program} apre le pagine senza sandbox. Per la sandbox, installa Safeer dal pacchetto .deb o come Flatpak."},
}


def omejeno(pot: str = OMEJITEV) -> bool:
    """Ali jedro omejuje uporabniske imenske prostore programom brez profila (Ubuntu 24.04+)."""
    try:
        with open(pot, encoding="ascii") as d:
            return d.read().strip() == "1"
    except (OSError, ValueError):
        return False


def oznaka(poti=OZNAKE) -> str:
    """Oznaka AppArmor tega procesa, npr. »safeer-os (unconfined)« ali »unconfined«; prazno, ce je ni."""
    for pot in poti:
        try:
            with open(pot, encoding="utf-8", errors="replace") as d:
                vrednost = d.read().strip("\0\n ")
            if vrednost:
                return vrednost
        except OSError:
            continue
    return ""


def nas_profil(vrednost: str) -> bool:
    return (vrednost or "").split(" ", 1)[0] in NASI_PROFILI


def bwrap_deluje(bwrap: str = BWRAP, cas: float = 10.0) -> bool:
    try:
        r = subprocess.run([bwrap, *POSKUS], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=cas, check=False)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def preveri(okolje: Optional[MutableMapping[str, str]] = None, pot_omejitve: str = OMEJITEV, poti_oznake=OZNAKE,
            bwrap: str = BWRAP) -> dict:
    """Stanje peskovnika: omejeno, oznaka, deluje (True, ce peskovnik WebKita lahko tece ali ga ni)."""
    okolje = os.environ if okolje is None else okolje
    stanje = {"omejeno": False, "oznaka": "", "deluje": True}
    if okolje.get("FLATPAK_ID") or str(okolje.get(IZKLOP, "0")) not in ("", "0") or not os.path.exists(bwrap):
        return stanje      # Flatpak (portal, ne bwrap), peskovnik ze izklopljen ali ga ni
    stanje["omejeno"] = omejeno(pot_omejitve)
    if not stanje["omejeno"]:
        return stanje      # Linux Mint, Debian, starejsi Ubuntu: bwrap dela kot vedno
    stanje["oznaka"] = oznaka(poti_oznake)
    if nas_profil(stanje["oznaka"]):
        return stanje      # nas profil z `userns` velja za ta proces in njegove otroke
    stanje["deluje"] = bwrap_deluje(bwrap)
    return stanje


def _izpisi(stanje: dict) -> None:
    print("[Safeer] peskovnik WebKit: jedro omejuje uporabniske imenske prostore (oznaka %r), bwrap ne deluje - "
          "strani tecejo brez peskovnika. Popravek: sudo apparmor_parser -r /etc/apparmor.d/<profil>"
          % (stanje["oznaka"] or "-"), flush=True)


def pripravi(okolje: Optional[MutableMapping[str, str]] = None, izpis: bool = True, **k) -> dict:
    """Ce peskovnik ne more teci, ga izklopi (namesto sesutja) in vrne stanje z »izklopljen«: True - klicatelj takrat
    enkrat pokaze pojasnilo (besedilo()). Z okoljem procesa samo prek pred_nitmi(): IZKLOP se DODA v okolje."""
    okolje = os.environ if okolje is None else okolje
    stanje = preveri(okolje, **k)
    stanje["izklopljen"] = False
    if not stanje["deluje"]:
        okolje[IZKLOP] = "1"
        stanje["izklopljen"] = True
        if izpis:
            _izpisi(stanje)
    return stanje


#: Stanje iz pred_nitmi() (None: v tem procesu se ni bilo klica).
_ob_zagonu: Optional[dict] = None


def pred_nitmi(okolje: Optional[MutableMapping[str, str]] = None, **k) -> dict:
    """Klici na zacetku programa, pred `import gi` (tece ena nit). IZKLOP se v okolje doda, ko bwrap ne dela; ko tecejo
    niti (uvoz GTK jih zazene), dodajanje spremenljivke ni varno (core/okolje_procesa.py) - prej se je to zgodilo v
    main(). Drug klic v istem procesu ne preverja znova in okolja ne spremeni."""
    global _ob_zagonu
    if _ob_zagonu is None:
        _ob_zagonu = pripravi(okolje, izpis=False, **k)
    return dict(_ob_zagonu)


def ob_zagonu() -> dict:
    """Stanje iz pred_nitmi() za main() - okolja ne spremeni. Zapis je tu, ker main() izpis ze preusmeri v sled.log
    (os_stabilnost.preusmeri_izpis). Ce pred_nitmi() ni bil klican (nov ali drugacen vstop v program), preverimo zdaj:
    zapis v okolje med tekom niti je redka nevarnost, WebKit brez peskovnika na Ubuntu 24.04+ pa bi zanesljivo koncal
    ves proces ob prvi strani (g_error)."""
    if _ob_zagonu is None:
        pred_nitmi()
    if _ob_zagonu["izklopljen"]:
        _izpisi(_ob_zagonu)
    return dict(_ob_zagonu)


def nas_izklop() -> bool:
    """Ali je IZKLOP v okolje procesa dal ta modul (bwrap tu ne dela), ne uporabnik sam pred zagonom programa."""
    return bool(_ob_zagonu and _ob_zagonu.get("izklopljen"))


def okolje_brez_izklopa(okolje: dict) -> dict:
    """Okolje za zunanji program (na mestu in vrne ga): brez nasega IZKLOP. Spremenljivko je dal ta proces zase - drug
    program (npr. GNOME Web ali Evolution s svojim profilom AppArmor, ki jima peskovnik dela) bi jo podedoval in tekel
    brez peskovnika. Okolje procesa ostane, kot je (AGENTS.md, Okolje procesa: podprocesu env=)."""
    if nas_izklop() and okolje.get(IZKLOP) == "1":
        del okolje[IZKLOP]
    return okolje


def besedilo(jezik: str, program: str, profil: str, mapa_profilov: str = "/etc/apparmor.d") -> tuple:
    """(naslov, besedilo) pojasnila v jeziku vmesnika (sl, en, de, es, fr, it; sicer anglesko). Brez nasega profila
    (AppImage, izvorna koda) ukaz apparmor_parser ne pomaga - takrat pojasnilo svetuje .deb ali Flatpak."""
    b = BESEDILA.get((jezik or "en")[:2].lower(), BESEDILA["en"])
    kljuc = "besedilo" if os.path.isfile(os.path.join(mapa_profilov, profil)) else "brez_profila"
    return b["naslov"], b[kljuc].format(program=program, profil=profil)


def pojasni_enkrat(mapa: str, posli) -> bool:
    """Pokliče posli() samo prvic (zapis v mapi nastavitev programa); vrne, ali je bilo pojasnilo poslano."""
    zapis = os.path.join(mapa, "peskovnik-pojasnjeno")
    if os.path.exists(zapis):
        return False
    try:
        os.makedirs(mapa, exist_ok=True)
        with open(zapis, "w", encoding="utf-8") as d:
            d.write("1\n")
    except OSError:
        return False
    posli()
    return True


def pojasni_kasneje(GLib, mapa: str, jezik: str, program: str, profil: str, app=None, zamik_s: int = 5) -> None:
    """Enkratno obvestilo (core/obvestila) nekaj sekund po zagonu, ko aplikacija ze tece na vodilu seje."""
    def posli() -> None:
        from core import obvestila
        naslov, vsebina = besedilo(jezik, program, profil)
        obvestila.poslji(naslov, vsebina, "safeer-peskovnik", app=app, prioriteta="high")
    GLib.timeout_add_seconds(zamik_s, lambda: (pojasni_enkrat(mapa, posli), False)[1])
