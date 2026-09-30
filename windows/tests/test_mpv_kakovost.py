"""Kakovosti HLS/DASH iz mpv track-list (brez libmpv: pogon z lažnim _mpv)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from safeer_windows import safeer_mpv_pogon as P


class _Mpv:
    track_list = [
        {"id": 2, "type": "video", "selected": False, "demux-w": 320, "demux-h": 180, "hls-bitrate": 275000},
        {"id": 1, "type": "video", "selected": True, "demux-w": 640, "demux-h": 360, "hls-bitrate": 880000},
        {"id": 3, "type": "video", "selected": False, "demux-w": 1920, "demux-h": 1080, "hls-bitrate": 12_000_000},
        {"id": 1, "type": "audio", "selected": True, "lang": "slv"},
        {"id": 1, "type": "sub", "selected": False, "title": "SL"},
    ]


def _pogon(mpv):
    p = object.__new__(P.SafeerMpvPogon); p._mpv = mpv; return p


def test_ime_kakovosti():
    assert P._ime_kakovosti({"id": 1, "demux-w": 1920, "demux-h": 1080, "hls-bitrate": 4_500_000}) == "1920×1080 · 4,5 Mb/s"
    assert P._ime_kakovosti({"id": 1, "demux-w": 3840, "demux-h": 2160, "hls-bitrate": 15_000_000}) == "3840×2160 · 15 Mb/s"
    assert P._ime_kakovosti({"id": 4}) == "Video 4"


def test_steze_video_urejene_od_najboljse():
    s = _pogon(_Mpv()).steze()
    assert [v["ime"] for v in s["video"]] == ["1920×1080 · 12 Mb/s", "640×360 · 0,9 Mb/s", "320×180 · 0,3 Mb/s"]
    assert s["trenutniVideo"] == 1 and s["zvok"][0]["ime"] == "slv" and s["podnapisi"][1]["ime"] == "SL"


def test_ena_video_sled_brez_izbire():
    m = _Mpv(); m.track_list = [t for t in _Mpv.track_list if t["type"] != "video" or t["id"] == 1]
    s = _pogon(m).steze()
    assert s["video"] == [] and s["trenutniVideo"] == 1
