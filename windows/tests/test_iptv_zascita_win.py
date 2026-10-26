"""Naloga 35 (lastnik 26. 10. 2026: »nevarnost zaklepa racuna je prioriteta«): zascita racuna IPTV v Windows
core/os_media.py, prenesena iz Linux izdaje 1.0.133 (mc-iptv-serije). Naslovi in racuni so izmisljeni (.test)."""
import tempfile
import threading
import time
import urllib.error

from core import os_media

RACUN = "http://ponudnik.test:8080/get.php?username=uporabnik&password=geslo&type=m3u_plus"
SEZNAM = b"#EXTM3U\n#EXTINF:-1,Kanal ena\nhttp://ponudnik.test:8080/live/uporabnik/geslo/1.ts\n"


def _mc(odgovori):
    """MediaCenter z laznim _download: odgovori so seznam (bajti ali izjema); klici se stejejo."""
    mc = os_media.MediaCenter(tempfile.mkdtemp(), roots=[])
    klici = []

    def prenesi(url):
        klici.append(url)
        o = odgovori.pop(0) if odgovori else SEZNAM
        if isinstance(o, Exception):
            raise o
        if isinstance(o, tuple):                         # (telo, vrsta vsebine)
            return o[0], o[1], url
        return o, "audio/x-mpegurl", url
    mc._download = prenesi
    mc._izmeri_ping = lambda *_a: None
    return mc, klici


def _zavrnitev():
    return urllib.error.HTTPError(RACUN, 403, "Forbidden", {}, None)


def _vir(mc, url=RACUN, **polja):
    data = mc._load()
    vir = dict({"id": "v1", "url": url, "ime": "Ponudnik", "posodobljeno": 0, "napaka": "", "stevilo": 0, "vnosi": []},
               **polja)
    data.setdefault("viri", []).append(vir)
    mc._save(data)
    return vir["id"]


def test_prejet_vir_z_racunom_ne_gre_na_omrezje():
    mc, klici = _mc([])
    r = mc.add_source(RACUN, "Ponudnik", prevzet={"tip": "url", "naslov": RACUN, "cas": 1})
    assert r["ok"] and r.get("caka") is True
    assert klici == [], "ob prejemu z druge naprave nobene prijave z geslom"
    assert mc.refresh_all()["rezultati"] == [] and klici == [], "skupna osvezitev cakajocega vira ne prenese"
    assert mc.refresh_stale()["osvezenih"] == 0 and klici == []
    assert mc.refresh_source(r["vir"]["id"])["ok"] and len(klici) == 1, "uporabnikov »Osvezi« da eno zahtevo"
    assert "caka_uporabnika" not in next(v for v in mc.sources() if v["id"] == r["vir"]["id"])


def test_premor_po_zavrnitvi_velja_tudi_za_osvezi():
    mc, klici = _mc([_zavrnitev()])
    ident = _vir(mc)
    r = mc.refresh_source(ident)
    assert not r["ok"] and len(klici) == 1
    for _ in range(10):                                  # 10 klikov »Osvezi« ni 10 prijav
        r = mc.refresh_source(ident)
        assert r["napaka"] == "premor" and r["premor_s"] > 0
    assert len(klici) == 1
    assert mc.refresh_stale(max_age=60)["osvezenih"] == 0 and len(klici) == 1
    napaka = str(next(v for v in mc._load()["viri"] if v["id"] == ident).get("napaka"))
    assert napaka and "geslo" not in napaka and "uporabnik" not in napaka, "sporocilo napake brez poverilnic"


def test_prazen_odgovor_racuna_brez_rezervne_zahteve():
    mc, klici = _mc([(b"<html>prijava</html>", "text/html")])       # racun potekel: prijavna stran namesto seznama
    vdelava = []
    os_media_resolve = os_media._resolve_embed_or_direct_source
    os_media._resolve_embed_or_direct_source = lambda *a: vdelava.append(a) or []
    try:
        ident = _vir(mc)
        r = mc.refresh_source(ident)
    finally:
        os_media._resolve_embed_or_direct_source = os_media_resolve
    assert not r["ok"] and len(klici) == 1 and vdelava == [], "brez druge zahteve z geslom (vdelava)"
    assert mc._zavrnjen_do(next(v for v in mc._load()["viri"] if v["id"] == ident)) > time.time()


def test_ena_osvezitev_vira_naenkrat():
    mc, klici = _mc([])
    ident = _vir(mc)
    vstop, sprosti = threading.Event(), threading.Event()
    pravi = mc._download

    def pocasen(url):
        vstop.set()
        sprosti.wait(5)
        return pravi(url)
    mc._download = pocasen
    t = threading.Thread(target=mc.refresh_source, args=(ident,))
    t.start()
    assert vstop.wait(5)
    assert mc.refresh_source(ident) == {"ok": False, "napaka": "", "ze_tece": True}
    sprosti.set()
    t.join(5)
    assert len(klici) == 1


def test_uspeh_odstrani_premor():
    mc, klici = _mc([])
    ident = _vir(mc, zavrnjen={"koda": 403, "ob": int(time.time()) - 700, "n": 1})   # prvi premor (600 s) je mimo
    assert mc.refresh_source(ident)["ok"] and len(klici) == 1
    assert "zavrnjen" not in next(v for v in mc._load()["viri"] if v["id"] == ident)
