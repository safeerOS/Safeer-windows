"""Naloga 27 (26. 10. 2026): Safeer OS za Windows ni nasel novih programov (paketi MSIX, Claude Code) in novih datotek
(znane mape na drugem disku, bliznjice Recent iz casa pred premikom map). Vse poti in imena so izmisljeni."""
import os
import struct
import sys
import threading
import time
import types

import pytest

from core import os_iskalnik
from safeer_windows import iskanje_win as iw, namizje_datoteke as nd, os_backend_win as ob

CLAUDE = "Claude_pzs8sxrjxfjjc!Claude"


@pytest.fixture
def paketi(monkeypatch):
    """Predpomnilnik paketnih aplikacij prazen; branje lupine zamenjano s stevcem klicev."""
    klici = []
    stanje = {"a": [("Claude", CLAUDE), ("Kalkulator", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")], "m": {}}
    monkeypatch.setattr(ob, "_PAKETNE", {"cas": -1e9, "seznam": [], "mape": {}, "z_mapami": False, "osvezujem": False})

    def beri(z_mapami):
        klici.append(z_mapami)
        return list(stanje["a"]), dict(stanje["m"])
    monkeypatch.setattr(ob, "_beri_appsfolder", beri)
    monkeypatch.setattr(ob, "shrani_shrambo", lambda podatki: True)
    monkeypatch.setattr(ob, "nalozi_shrambo", lambda: {"pogosti": {}})
    return klici, stanje


@pytest.fixture
def prazen_start(monkeypatch, tmp_path):
    """Meni Start in namizje v zacasni mapi (brez lastnikovih bliznjic), domaca mapa tudi."""
    for ime in ("ProgramData", "APPDATA", "USERPROFILE", "PUBLIC", "HOME"):
        (tmp_path / ime).mkdir()
        monkeypatch.setenv(ime, str(tmp_path / ime))
    meni = tmp_path / "APPDATA" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    meni.mkdir(parents=True)
    return meni


# ------------------------------------------------------------------ paketne aplikacije
def test_razberi_appsfolder_samo_pravi_paketi():
    podatki = {"a": [{"i": "Claude", "a": CLAUDE},
                     {"i": "Office 2016 Upload Center", "a": "zn=BV5!!!!4!!!!MKKSkWxpFiles<"},
                     {"i": "Get Help", "a": "Microsoft.GetHelp_8wekyb3d8bbwe!App"},
                     {"i": "Notification Manager for Adobe Acrobat", "a": "AcrobatNotificationClient_e1rzdqpraam7r!App"},
                     {"i": "Zlo", "a": "Zlo_pzs8sxrjxfjjc!App & calc"},
                     {"i": "Explorer", "a": "Microsoft.Windows.Explorer"}],
               "m": {"d": "Claude_pzs8sxrjxfjjc", "p": "C:\\Program Files\\WindowsApps\\Claude"}}
    aplikacije, mape = ob._razberi_appsfolder(podatki)
    assert aplikacije == [("Claude", CLAUDE)]
    assert mape == {"Claude_pzs8sxrjxfjjc": "C:\\Program Files\\WindowsApps\\Claude"}
    assert ob._razberi_appsfolder({"a": {"i": "Claude", "a": CLAUDE}})[0] == [("Claude", CLAUDE)]  # en element
    assert ob._razberi_appsfolder("ni slovar") == ([], {})


@pytest.mark.skipif(sys.platform != "win32", reason="meni Start Windows")
def test_seznam_ima_paketne_bliznjica_ima_prednost(paketi, prazen_start):
    (prazen_start / "Kalkulator.lnk").write_bytes(b"L\x00\x00\x00")
    programi = ob.poisci_start_menu_programe(z_ikonami=False)
    po_imenu = {p["ime"]: p for p in programi}
    assert po_imenu["Claude"]["pot"] == "shell:AppsFolder\\" + CLAUDE
    assert po_imenu["Claude"]["id"].startswith("win_pkg_")
    assert po_imenu["Kalkulator"]["pot"].endswith("Kalkulator.lnk"), ".lnk ima prednost pred paketom"
    assert sum(1 for p in programi if p["ime"] == "Kalkulator") == 1


def test_predpomnilnik_paketnih(paketi, monkeypatch):
    klici, stanje = paketi
    ura = [1000.0]
    monkeypatch.setattr(ob.time, "monotonic", lambda: ura[0])
    assert ob.paketne_aplikacije() == stanje["a"]
    ura[0] += 30
    ob.paketne_aplikacije()
    assert len(klici) == 1, "v 60 s brez novega klica lupine"
    stanje["a"].append(("Novo", "Novo.App_aaaaaaaaaaaaa!App"))
    ura[0] += 61
    zadrzi = threading.Event()
    prejsnje = ob._beri_appsfolder
    monkeypatch.setattr(ob, "_beri_appsfolder", lambda z: (zadrzi.wait(5), prejsnje(z))[1])  # lupina je pocasna
    staro = ob.paketne_aplikacije()  # odgovori takoj s starim, osvezi v ozadju
    assert ("Novo", "Novo.App_aaaaaaaaaaaaa!App") not in staro
    zadrzi.set()
    for _ in range(200):
        if not ob._PAKETNE["osvezujem"]:
            break
        time.sleep(0.01)
    assert ("Novo", "Novo.App_aaaaaaaaaaaaa!App") in ob.paketne_aplikacije()
    assert len(klici) == 2


def test_zagon_paketa_brez_lupine(paketi, monkeypatch):
    zagnani = []
    monkeypatch.setattr(ob.subprocess, "Popen", lambda argv, **k: zagnani.append(argv))
    assert ob.zazeni_program("shell:AppsFolder\\" + CLAUDE)
    assert zagnani == [["explorer.exe", "shell:AppsFolder\\" + CLAUDE]]
    for zlo in ('shell:AppsFolder\\Claude_pzs8sxrjxfjjc!Claude & calc', 'shell:AppsFolder\\x"|calc',
                "shell:AppsFolder\\..\\..\\Windows\\notepad.exe", "shell:AppsFolder\\Claude_pzs8sxrjxfjjc!Claude\r\nx"):
        assert not ob.zazeni_program(zlo), zlo
    assert len(zagnani) == 1


def test_ikona_iz_manifesta(tmp_path):
    (tmp_path / "Assets").mkdir()
    png = b"\x89PNG\r\n\x1a\nikona"
    (tmp_path / "Assets" / "Square44x44Logo.scale-100.png").write_bytes(b"\x89PNG\r\n\x1a\nmala")
    (tmp_path / "Assets" / "Square44x44Logo.targetsize-48.png").write_bytes(png)
    (tmp_path / "AppxManifest.xml").write_text(
        '<Package><Applications><Application Id="Claude"><uap:VisualElements Square44x44Logo="Assets\\Square44x44Logo.png"/>'
        '</Application></Applications></Package>', encoding="utf-8")
    uri = ob._logotip_paketa(str(tmp_path), "Claude")
    assert uri.startswith("data:image/png;base64,")
    import base64
    assert base64.b64decode(uri.split(",", 1)[1]) == png
    (tmp_path / "AppxManifest.xml").write_text('<Application Id="Claude" Square44x44Logo="..\\..\\skrivno.png"/>',
                                               encoding="utf-8")
    assert ob._logotip_paketa(str(tmp_path), "Claude") == "", "pot iz manifesta ne sme iz mape paketa"


# ------------------------------------------------------------------ Claude Code
def test_claude_code_najden_in_odprt_v_konzoli(paketi, prazen_start, monkeypatch, tmp_path):
    dom = tmp_path / "USERPROFILE"
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(dom), 1))
    monkeypatch.setattr(ob.shutil, "which", lambda ukaz: None)
    assert ob._ukazni_program("claude-code") == ""
    (dom / ".local" / "bin").mkdir(parents=True)
    exe = dom / ".local" / "bin" / "claude.exe"
    exe.write_bytes(b"MZ")
    assert ob._ukazni_program("claude-code") == str(exe)
    programi = {p["ime"]: p for p in ob.poisci_start_menu_programe(z_ikonami=False)}
    assert programi["Claude Code"]["pot"] == "cli:claude-code"
    zagnani = []
    monkeypatch.setattr(ob.subprocess, "Popen", lambda argv, **k: zagnani.append((argv, k.get("cwd"))))
    assert ob.zazeni_program(programi["Claude Code"]["id"])
    assert zagnani == [([str(exe)], str(dom))]


# ------------------------------------------------------------------ znane mape in iskanje
def test_mape_glavnega_okna_iz_registra(monkeypatch, tmp_path):
    d = tmp_path / "D" / "Dokumenti"
    d.mkdir(parents=True)
    monkeypatch.setattr(ob, "znane_mape", lambda: {"DOCUMENTS": str(d), "DESKTOP": str(tmp_path / "ni")})
    mape = {m["vrsta"]: m["pot"] for m in ob.uporabniske_mape()}
    assert mape.get("DOCUMENTS") == str(d)
    assert "DESKTOP" not in mape


def test_korenine_brez_podvojenih():
    dom = os.path.abspath(os.sep + "dom")
    mape = [{"vrsta": "HOME", "pot": dom}]
    assert iw.korenine(mape, dom) == [dom]


def test_iskanje_najde_novo_datoteko_na_drugem_disku(monkeypatch, tmp_path):
    dom, dok = tmp_path / "dom", tmp_path / "D" / "Dokumenti"
    (dom / "Prenosi").mkdir(parents=True)
    (dok / "projekt").mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(dom), 1))
    monkeypatch.setattr(os_iskalnik, "_indeks", None)
    monkeypatch.setattr(iw, "_indeksi", {})
    mape = lambda: [{"vrsta": "HOME", "pot": str(dom)}, {"vrsta": "DOCUMENTS", "pot": str(dok)}]  # noqa: E731
    assert iw.isci("racun", mape=mape) == []
    (dok / "projekt" / "Račun 2026.pdf").write_bytes(b"x")
    iw.zastarel()
    time.sleep(0.05)
    os_iskalnik.indeks().zgrajen = iw._indeksi[os.path.normcase(str(dok))].zgrajen = -1e9  # oba indeksa stara
    for _ in range(100):
        zadetki = iw.isci("racun 2026", mape=mape)
        if zadetki:
            break
        time.sleep(0.05)
    assert [z["ime"] for z in zadetki] == ["Račun 2026.pdf"]
    assert os.path.normcase(zadetki[0]["pot"]) == os.path.normcase(str(dok / "projekt" / "Račun 2026.pdf"))


# ------------------------------------------------------------------ nedavne
def bliznjica(pot: str, unicode: bool = False) -> bytes:
    """Izmisljena .lnk z LinkInfo (VolumeIDAndLocalBasePath) po MS-SHLLINK 2.3."""
    glava = struct.pack("<I16sI", 0x4C, bytes.fromhex("0114020000000000c000000000000046"), 0x2 | 0x80)
    glava += b"\x00" * (0x4C - len(glava))
    osnova_a = pot.encode("ascii", "replace") + b"\x00"
    vel_glave = 0x24 if unicode else 0x1C
    volume = struct.pack("<IIII", 0x11, 3, 0, 0x10) + b"\x00"
    od_vol = vel_glave
    od_osn = od_vol + len(volume)
    od_pri = od_osn + len(osnova_a)
    telo = volume + osnova_a + b"\x00"
    dodatno = b""
    if unicode:
        od_osn_u = od_pri + 1
        osnova_u = pot.encode("utf-16-le") + b"\x00\x00"
        dodatno = osnova_u + b"\x00\x00"
        polja = struct.pack("<II", od_osn_u, od_osn_u + len(osnova_u))
    else:
        polja = b""
    vel = vel_glave + len(telo) + len(dodatno)
    li = struct.pack("<IIIIIII", vel, vel_glave, 1, od_vol, od_osn, 0, od_pri) + polja + telo + dodatno
    return glava + li


def test_cilj_bliznjice_ansi_in_unicode():
    assert nd.cilj_bliznjice(bliznjica("C:\\x\\a.txt")) == "C:\\x\\a.txt"
    assert nd.cilj_bliznjice(bliznjica("C:\\x\\Poročilo.docx", unicode=True)) == "C:\\x\\Poročilo.docx"


def test_preslikava_stare_poti_po_premiku_map():
    dom = os.path.join(os.sep, "dom")
    znane = {"DOCUMENTS": os.path.join("D:" + os.sep, "Dokumenti"), "DESKTOP": os.path.join(dom, "Desktop")}
    stara = os.path.join(dom, "Documents", "mapa", "a.txt")
    assert nd.preslikaj_premaknjeno(stara, znane, dom) == os.path.join(znane["DOCUMENTS"], "mapa", "a.txt")
    namizje = os.path.join(dom, "Desktop", "b.txt")
    assert nd.preslikaj_premaknjeno(namizje, znane, dom) == namizje, "neprestavljena mapa ostane"
    drugo = os.path.join("E:" + os.sep, "c.txt")
    assert nd.preslikaj_premaknjeno(drugo, znane, dom) == drugo


def test_nedavne_iz_premaknjenih_in_novih(monkeypatch, tmp_path):
    dom, dok = tmp_path / "dom", tmp_path / "D" / "Dokumenti"
    recent = tmp_path / "Recent"
    for m in (dom, dok / "stara", recent):
        m.mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(dom), 1))
    # bliznjica iz casa pred premikom: kaze na dom\Documents\stara\porocilo.txt, datoteka je zdaj v D:\Dokumenti
    (dok / "stara" / "porocilo.txt").write_text("x")
    star = time.time() - 40 * 86400
    os.utime(dok / "stara" / "porocilo.txt", (star, star))
    (recent / "porocilo.txt.lnk").write_bytes(bliznjica(str(dom / "Documents" / "stara" / "porocilo.txt")))
    os.utime(recent / "porocilo.txt.lnk", (time.time() - 5 * 86400, time.time() - 5 * 86400))  # odprta pred 5 dnevi
    # nova datoteka, ki je ni nihce odprl (Recent je ne pozna)
    (dok / "nova.pdf").write_bytes(b"%PDF")
    (dok / "~$zaklep.docx").write_bytes(b"x")
    znane = {"DOCUMENTS": str(dok)}
    imena = [e["ime"] for e in nd.nedavne(znane=znane, recent=str(recent))]
    assert imena[0] == "nova.pdf"
    assert "porocilo.txt" in imena
    assert "~$zaklep.docx" not in imena


def test_sledenje_nedavnim_izklopljeno(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("register Windows")
    vrednosti = {"Start_TrackDocs": 0}

    class Kljuc:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    lazni = types.SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, OpenKey=lambda k, p: Kljuc(),
                                  QueryValueEx=lambda k, ime: (vrednosti[ime], 4) if ime in vrednosti else
                                  (_ for _ in ()).throw(OSError()))
    monkeypatch.setitem(sys.modules, "winreg", lazni)
    assert nd.sledenje_nedavnim() is False
    vrednosti["Start_TrackDocs"] = 1
    assert nd.sledenje_nedavnim() is True
