"""Preverba slike oddaljenega zaslona v zamrznjenem paketu (CI): zajem zaslona v H.264 kot pri deljenju zaslona in
dekodiranje kot v gledalcu oddaljenega zaslona.

Uradni paket do 25. 10. 2026 PyAV ni imel (ni ga bilo v windows/requirements.txt), Pillow pa je gradnja izpustila
(--exclude-module PIL): deljenje zaslona je napravi vrnilo »Na racunalniku manjka kodirnik slike (PyAV)«, gledalec
slike ni dekodiral, »Deli z« ni zajel zaslona. Preizkusi iz izvora tega ne vidijo (tam je vse namesceno), zato CI to
pozene v zgrajenem SafeerOS.exe (build_windows.py kodek-frozen). Vsak korak je v porocilu posebej.
"""

from __future__ import annotations

import json
import os
import time

#: Toliko kosov H.264 mora priti iz zajema in vsaj eden se mora dekodirati v sliko pravih mer.
KOSOV = 3
ROK_S = 30.0


def _zapisi(izid: dict, porocilo: str) -> dict:
    izid["ok"] = bool(izid["koraki"]) and all(k.get("ok") for k in izid["koraki"].values())
    if porocilo:
        os.makedirs(os.path.dirname(os.path.abspath(porocilo)) or ".", exist_ok=True)
        with open(porocilo, "w", encoding="utf-8") as d:
            json.dump(izid, d, ensure_ascii=False, indent=2)
    return izid


def preveri(porocilo: str = "", kosov: int = KOSOV, rok_s: float = ROK_S) -> dict:
    """Vrne {"ok": bool, "koraki": {...}}; ce je dano `porocilo`, ga zapise kot JSON."""
    izid = {"ok": False, "koraki": {}}
    koraki = izid["koraki"]
    try:
        from PIL import Image, ImageGrab  # noqa: F401  (slicice, »Deli z«, zajem GDI)
        import PIL
        koraki["pillow"] = {"ok": True, "razlicica": getattr(PIL, "__version__", "")}
    except Exception as e:  # noqa: BLE001 - porocilo pove, kaj manjka
        koraki["pillow"] = {"ok": False, "napaka": repr(e)}
    try:
        import av
        from av.video.reformatter import VideoReformatter
        koraki["pyav"] = {"ok": True, "razlicica": getattr(av, "__version__", ""),
                          "ffmpeg": str(getattr(av, "ffmpeg_version_info", ""))}
    except Exception as e:  # noqa: BLE001
        koraki["pyav"] = {"ok": False, "napaka": repr(e)}
        return _zapisi(izid, porocilo)

    # Deljenje zaslona: isti razred kot seja (navidezni_zaslon -> zajem_zaslona.H264Zajem).
    kosi = []
    try:
        from . import zajem_zaslona
        zajem = zajem_zaslona.H264Zajem(fps=30)
        konec = time.monotonic() + rok_s
        try:
            for kos in zajem.okvirji(lambda: time.monotonic() < konec and len(kosi) < kosov):
                kosi.append(kos)
        finally:
            zajem.zapri()
        koraki["zajem"] = {"ok": len(kosi) >= kosov, "kodirnik": zajem.kodirnik, "mere": [zajem.sirina, zajem.visina],
                           "dxgi": getattr(zajem, "_dxgi", None) is not None, "kosov": len(kosi),
                           "bajtov": sum(len(k) for k in kosi)}
    except Exception as e:  # noqa: BLE001
        koraki["zajem"] = {"ok": False, "napaka": repr(e)}
        return _zapisi(izid, porocilo)

    # Gledalec: isti dekoder in pretvorba kot oddaljeni_zaslon._DekodirnaNit / _pretvarjaj.
    try:
        dekoder = av.CodecContext.create("h264", "r")
        try:
            dekoder.thread_type = "SLICE"
        except Exception:  # noqa: BLE001
            pass
        slike = []
        for kos in kosi:
            for paket in dekoder.parse(kos):
                slike.extend(dekoder.decode(paket))
        try:
            for paket in dekoder.parse(None):
                slike.extend(dekoder.decode(paket))
            slike.extend(dekoder.decode(None))
        except Exception:  # noqa: BLE001 - praznjenje ni del seje gledalca
            pass
        mere = [[s.width, s.height] for s in slike]
        bgra = VideoReformatter().reformat(slike[-1], format="bgra") if slike else None
        prava = [zajem.sirina, zajem.visina]
        koraki["gledalec"] = {"ok": bool(slike) and all(m == prava for m in mere) and bgra is not None
                              and int(bgra.planes[0].line_size) >= prava[0] * 4,
                              "slik": len(slike), "mere": mere[:3]}
    except Exception as e:  # noqa: BLE001
        koraki["gledalec"] = {"ok": False, "napaka": repr(e)}
    return _zapisi(izid, porocilo)
