"""Utrjenost datotek PE (exe/dll) brez zunanjih orodij - ustreznica readelf za Windows (Safeer, 25. 10. 2026).

Bere glavo PE: DllCharacteristics (ASLR /DYNAMICBASE, HIGH_ENTROPY_VA, DEP /NXCOMPAT, CFG /guard:cf),
Load Config (GuardFlags: CF instrumentirano, SecurityCookie = /GS), Debug directory tip 20 (EX_DLLCHARACTERISTICS:
CET shadow stack /CETCOMPAT), tip 13 (POGO: povezovalnik MSVC z LTCG/PGO).
Raba: python pe_utrjenost.py MAPA|DATOTEKA ... [--preveri] [--izjeme pe_izjeme.json] [--porocilo izid.json]

Preverba paketa v CI (lastnik, 21. 10. 2026: vsaka nasa knjiznica in program sta utrjena vsaj kot paket distribucije):
ASLR, DEP in HEVA (64-bit) mora imeti VSAKA datoteka; nasi programi se CFG, /GS in CET; tuje knjiznice brez katere
od teh samo z zapisano izjemo in razlogom (windows/tools/pe_izjeme.json). Manjkajoca zascita brez izjeme ustavi gradnjo.
"""
import hashlib
import json
import os
import struct
import sys

DYNAMIC_BASE = 0x0040
HIGH_ENTROPY_VA = 0x0020
NX_COMPAT = 0x0100
GUARD_CF = 0x4000
CF_INSTRUMENTED = 0x00000100
CETCOMPAT = 0x01


def _odmik(sekcije, rva):
    for va, vsize, raw, rawsize in sekcije:
        if va <= rva < va + max(vsize, rawsize):
            return raw + (rva - va)
    return None


def preberi(pot):
    with open(pot, "rb") as f:
        p = f.read()
    if p[:2] != b"MZ":
        return {"napaka": "ni PE"}
    e = struct.unpack_from("<I", p, 0x3C)[0]
    if p[e:e + 4] != b"PE\0\0":
        return {"napaka": "ni PE"}
    stroj, nsek = struct.unpack_from("<HH", p, e + 4)
    velopt = struct.unpack_from("<H", p, e + 20)[0]
    opt = e + 24
    pe32p = struct.unpack_from("<H", p, opt)[0] == 0x20B
    dllch = struct.unpack_from("<H", p, opt + 70)[0]
    dd = opt + (112 if pe32p else 96)
    ndd = struct.unpack_from("<I", p, dd - 4)[0]

    def imenik(i):
        return struct.unpack_from("<II", p, dd + 8 * i) if i < ndd else (0, 0)

    sek = []
    for i in range(nsek):
        b = opt + velopt + 40 * i
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", p, b + 8)
        sek.append((va, vsize, raw, rawsize))
    izid = {
        "x64": stroj == 0x8664,
        "ASLR": bool(dllch & DYNAMIC_BASE),
        "HEVA": bool(dllch & HIGH_ENTROPY_VA),
        "DEP": bool(dllch & NX_COMPAT),
        "CFG": bool(dllch & GUARD_CF),
        "CFG_instr": False,
        "GS": False,
        "CET": False,
        "POGO": False,
        "PDB": "",
    }
    rva, _ = imenik(10)  # Load Config
    if rva:
        o = _odmik(sek, rva)
        if o is not None:
            dolzina = struct.unpack_from("<I", p, o)[0]
            if pe32p:
                if dolzina >= 0x60:
                    izid["GS"] = struct.unpack_from("<Q", p, o + 0x58)[0] != 0
                if dolzina >= 0x94:
                    gf = struct.unpack_from("<I", p, o + 0x90)[0]
                    izid["CFG_instr"] = bool(gf & CF_INSTRUMENTED)
                    izid["GuardFlags"] = hex(gf)
            else:
                if dolzina >= 0x40:
                    izid["GS"] = struct.unpack_from("<I", p, o + 0x3C)[0] != 0
                if dolzina >= 0x5C:
                    izid["CFG_instr"] = bool(struct.unpack_from("<I", p, o + 0x58)[0] & CF_INSTRUMENTED)
    rva, vel = imenik(6)  # Debug directory
    if rva:
        o = _odmik(sek, rva)
        if o is not None:
            for i in range(vel // 28):
                b = o + 28 * i
                tip, velp, _, raw = struct.unpack_from("<IIII", p, b + 12)
                if tip == 20 and raw and velp >= 4:
                    izid["CET"] = bool(struct.unpack_from("<I", p, raw)[0] & CETCOMPAT)
                elif tip == 13:
                    izid["POGO"] = True
                elif tip == 2 and raw and velp > 24 and p[raw:raw + 4] == b"RSDS":
                    izid["PDB"] = p[raw + 24:raw + velp].split(b"\0")[0].decode("utf-8", "replace")[-90:]
    return izid


# ------------------------------------------------------------------ preverba paketa (CI)
#: Zascite, ki jih mora imeti VSAKA datoteka PE v paketu (nasa ali tuja). HEVA samo za 64-bitne.
OBVEZNO_VSEM = ("ASLR", "DEP", "HEVA")
#: Nase datoteke: poleg tega se CFG, /GS in CET (lastnik, 21. 10. 2026: »ce imamo te ranljivosti, nismo zares Safeer«).
OBVEZNO_NASIM = ("CFG", "GS", "CET")
NASE = ("safeerbrowser.exe", "safeeros.exe", "safeercontrol.exe", "safeermediawebview.exe", "safeer-drm.exe",
        "safeerpredvajalnik.exe",
        # libmpv gradimo sami (safeerOS/milutv-libmpv): zanj velja isto kot za nase programe.
        "libmpv-2.dll")


_GO_ZNAKI = (b"\xff Go buildinf:", b"Go build ID:")
#: Koncnice, ki jih preverimo vedno; druge datoteke samo, ce imajo glavo PE (Grok W16: .ocx, .cpl, brez koncnice ...).
_KONCNICE_PE = (".exe", ".dll", ".pyd")


def _konec_odsekov(p):
    """Konec zadnjega odseka v datoteki; za njim je prekrivek (npr. arhiv modulov PyInstaller)."""
    try:
        e = struct.unpack_from("<I", p, 0x3C)[0]
        if p[e:e + 4] != b"PE\0\0":
            return 0
        nsek = struct.unpack_from("<H", p, e + 6)[0]
        velopt = struct.unpack_from("<H", p, e + 20)[0]
        konec = 0
        for i in range(nsek):
            rawsize, raw = struct.unpack_from("<II", p, e + 24 + velopt + 40 * i + 16)
            konec = max(konec, raw + rawsize)
        return min(konec, len(p))
    except struct.error:
        return 0


def je_go(pot):
    """Program, preveden z Go (zaganjalnik): povezovalnik Go ne zna /guard:cf, /GS in /CETCOMPAT. Znak gradnje Go
    mora biti v odsekih programa, ne v prekrivku - arhiv PyInstaller lahko nosi poljuben niz (pregled Grok W15)."""
    with open(pot, "rb") as f:
        p = f.read()
    konec = _konec_odsekov(p)
    return any(p.find(znak, 0, konec) >= 0 for znak in _GO_ZNAKI)


def je_pe(pot):
    """Ali ima datoteka glavo PE (MZ + PE\\0\\0), ne glede na koncnico."""
    try:
        with open(pot, "rb") as f:
            g = f.read(64)
            if len(g) < 64 or g[:2] != b"MZ":
                return False
            f.seek(struct.unpack_from("<I", g, 0x3C)[0])
            return f.read(4) == b"PE\0\0"
    except (OSError, struct.error):
        return False


def sha256(pot):
    h = hashlib.sha256()
    with open(pot, "rb") as f:
        for kos in iter(lambda: f.read(1 << 20), b""):
            h.update(kos)
    return h.hexdigest()


def je_nas(ime):
    """Nas program ali knjiznica: zahtevamo CFG, /GS in CET; izjema samo z rokom (Grok W14, W17)."""
    ime = str(ime or "").lower()
    return ime in NASE or ime.startswith("safeer")


def _izjema(ime, izjeme, pot="", sha=None, danes=None):
    """Izjema za datoteko: {"dovoli", "razlog", "opozorilo", "rok", "vzorec"}. Vzorec fnmatch na ime ali na pot (z /,
    male crke); prvi ujemajoci se vzorec velja. Izjema s kljucem "sha256" ({ime: vsota}) velja samo za datoteko s
    pripeto vsoto (tuja knjiznica, ki je ne gradimo - npr. FFmpeg v PySide6, OpenBLAS v numpy): nova razlicica
    ustavi gradnjo, dokler je kdo ne pregleda (koordinator 25. 10. 2026: izjema z razlogom, ne tiho). Za NAS program
    velja izjema samo z rokom ("rok": "LLLL-MM-DD") in samo do roka (pregled Grok W14). `sha` je vsota datoteke ali
    funkcija, ki jo izracuna (samo, ko jo izjema zahteva)."""
    import datetime
    import fnmatch
    nic = {"dovoli": set(), "razlog": "", "opozorilo": "", "rok": "", "vzorec": ""}
    pot = str(pot or ime).replace("\\", "/").lower()
    for vzorec, podatki in izjeme.items():
        v = vzorec.lower()
        if not (fnmatch.fnmatch(ime.lower(), v) or ("/" in v and fnmatch.fnmatch(pot, v))):
            continue
        izid = dict(nic, vzorec=vzorec)
        pripete = podatki.get("sha256")
        if pripete is not None:
            vsota = (sha() if callable(sha) else sha) or ""
            dovoljene = pripete.get(ime.lower(), []) if isinstance(pripete, dict) else []
            dovoljene = [dovoljene] if isinstance(dovoljene, str) else list(dovoljene)
            if vsota.lower() not in [str(d).lower() for d in dovoljene]:
                izid["opozorilo"] = "SHA-256 %s ni pripeta v izjemi %s (%s) - nova razlicica: preglej" % (
                    vsota or "?", vzorec, podatki.get("razlicica", ""))
                return izid
        rok = str(podatki.get("rok") or "")
        if je_nas(ime):
            danes = danes or datetime.date.today().isoformat()
            if not rok:
                izid["opozorilo"] = "izjema %s za nas program nima roka - nasi programi so utrjeni v celoti" % vzorec
                return izid
            if rok < danes:
                izid["opozorilo"] = "izjema %s za nas program je potekla %s" % (vzorec, rok)
                return izid
        izid.update(dovoli=set(podatki.get("dovoli", [])), razlog=str(podatki.get("razlog", "")), rok=rok)
        return izid
    return nic


def odlocitev(ime, izid, go, izjeme, pot="", sha=None, danes=None):
    """Kaj manjka in ni izjema (prazen seznam = v redu) in katere izjeme so bile uporabljene (z razlogom)."""
    if "napaka" in izid:
        return ["ni PE: " + izid["napaka"]], []
    zahtevano = [z for z in OBVEZNO_VSEM if z != "HEVA" or izid.get("x64")]
    if ime.lower() in NASE:
        zahtevano += list(OBVEZNO_NASIM)
    manjka = [z for z in zahtevano if not izid.get(z)]
    if ime.lower() not in NASE:
        # Tuje knjiznice: CFG, /GS in CET se izmerijo; brez njih so dovoljene samo z zapisano izjemo.
        manjka += [z for z in ("CFG", "GS", "CET") if not izid.get(z) and z not in manjka]
    iz = _izjema(ime, izjeme, pot, sha, danes) if manjka else {"dovoli": set(), "razlog": "", "opozorilo": "",
                                                              "rok": "", "vzorec": ""}
    dovoli, razlog = set(iz["dovoli"]), iz["razlog"]
    if go:
        dovoli |= {"CFG", "GS", "CET"}
        razlog = "Go: povezovalnik ne podpira /guard:cf, /GS in /CETCOMPAT (ASLR, HEVA, DEP ima)"
    napake = [z for z in manjka if z not in dovoli or z in OBVEZNO_VSEM]
    if napake and iz["opozorilo"]:
        napake.append(iz["opozorilo"])
    uporabljene = [z for z in manjka if z in dovoli and z not in OBVEZNO_VSEM]
    if not uporabljene:
        return napake, []
    return napake, [{"manjka": uporabljene, "razlog": razlog, "rok": "" if go else iz["rok"],
                     "vzorec": "go" if go else iz["vzorec"]}]


def preveri(poti, izjeme, danes=None):
    """Vse datoteke PE v poteh (.exe/.dll/.pyd in vse drugo z glavo PE) -> (porocilo, stevilo napak)."""
    porocilo, napak = {}, 0
    for arg in poti:
        datoteke = []
        if os.path.isdir(arg):
            for koren, _, imena in os.walk(arg):
                for d in imena:
                    p = os.path.join(koren, d)
                    if d.lower().endswith(_KONCNICE_PE) or je_pe(p):
                        datoteke.append(p)
        elif os.path.isfile(arg):
            datoteke = [arg]
        for pot in sorted(datoteke):
            try:
                izid = preberi(pot)
                go = je_go(pot)
            except Exception as e:  # noqa: BLE001 - neberljiva datoteka je napaka preverbe
                izid, go = {"napaka": str(e)}, False
            rel = os.path.relpath(pot, arg) if os.path.isdir(arg) else pot
            n, u = odlocitev(os.path.basename(pot), izid, go, izjeme, rel, sha=lambda p=pot: sha256(p), danes=danes)
            porocilo[pot] = dict(izid, go=go, napake=n, izjeme=u)
            napak += bool(n)
    return porocilo, napak


def napake_izjem(izjeme):
    """Izjema brez razloga ali brez seznama »dovoli« je napaka seznama (Grok W17)."""
    return ["izjema %s nima razloga" % v for v, d in izjeme.items() if not str(d.get("razlog") or "").strip()] + \
           ["izjema %s nima seznama dovoli" % v for v, d in izjeme.items() if not d.get("dovoli")]


def main():
    import argparse
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("poti", nargs="+")
    a.add_argument("--preveri", action="store_true", help="napaka (izhod 1), ce kaksni datoteki manjka zascita")
    a.add_argument("--izjeme", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "pe_izjeme.json"))
    a.add_argument("--porocilo", default="")
    arg = a.parse_args()
    with open(arg.izjeme, encoding="utf-8") as f:
        izjeme = json.load(f)["izjeme"]
    slabe = napake_izjem(izjeme)
    for n in slabe:
        print("NAPAKA seznama izjem: " + n)
    if slabe and arg.preveri:
        return 2
    porocilo, napak = preveri(arg.poti, izjeme)
    if arg.porocilo:
        os.makedirs(os.path.dirname(os.path.abspath(arg.porocilo)), exist_ok=True)
        with open(arg.porocilo, "w", encoding="utf-8") as f:
            json.dump(porocilo, f, indent=1, ensure_ascii=False)
    for pot, r in porocilo.items():
        if r["napake"]:
            print("NAPAKA %s: manjka %s" % (pot, ", ".join(r["napake"])))
    uporabljeni = set()
    for pot, r in porocilo.items():
        for u in r["izjeme"]:
            uporabljeni.add(u.get("vzorec", ""))
            if u.get("rok"):
                # Nas program brez polne zascite: vidno v CI kot opozorilo, do roka (Grok W14).
                print("::warning::%s: manjka %s - izjema do %s (%s)" % (pot, ", ".join(u["manjka"]), u["rok"],
                                                                         u["razlog"][:120]))
    neuporabljene = [v for v in izjeme if v not in uporabljeni]
    if neuporabljene:
        print("Neuporabljene izjeme (preveri, ali so se potrebne): " + ", ".join(neuporabljene))
    print("PE: %d datotek, %d z manjkajoco zascito, %d z izjemo" % (
        len(porocilo), napak, sum(1 for r in porocilo.values() if r["izjeme"])))
    return 1 if (arg.preveri and napak) else 0


if __name__ == "__main__":
    sys.exit(main())
