from safeer_windows import os_backend_win as b


def test_drm_storitve_prepoznane():
    for url in ("https://www.netflix.com/browse", "https://netflix.com", "https://www.disneyplus.com/sl-si",
                "https://www.primevideo.com/", "https://open.spotify.com/", "https://www.amazon.com/gp/video/x"):
        assert b.je_drm_storitev(url), url


def test_ne_drm_ostane_v_spletu():
    for url in ("https://www.youtube.com/", "https://amazon.com/dp/123", "https://notnetflix.com/",
                "https://netflix.com.evil.si/", "file:///C:/x", "", "javascript:alert(1)"):
        assert not b.je_drm_storitev(url), url
