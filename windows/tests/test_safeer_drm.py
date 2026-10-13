"""Safeer DRM (castLabs ECS, Widevine) kot prvi vdelani predvajalnik; WebView2 ostane rezerva."""
from pathlib import Path
import unittest

KOREN = Path(__file__).resolve().parents[2]
MEDIA = (KOREN / "windows" / "safeer_windows" / "webview2_media.py").read_text(encoding="utf-8")
APP = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
POLICY = (KOREN / "windows" / "safeer_windows" / "policy.py").read_text(encoding="utf-8")
OS_JS = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")


class SafeerDrmTest(unittest.TestCase):
    def test_drm_je_prvi_webview2_rezerva(self):
        self.assertIn('koren_paketa / "SafeerDRM" / "safeer-drm.exe"', MEDIA)
        self.assertIn("self.drm_executable if self.drm_executable.is_file() else self.webview2_executable", MEDIA)

    def test_okno_je_vdelano_v_safeer_os(self):
        # Uporabnik ne vidi drugega okna: rocaj iz dnevnika, WS_CHILD, SetParent v ploskev predvajalnika.
        self.assertIn('vrsta == "WINDOW_HANDLE"', MEDIA)
        self.assertIn("user32.SetParent(rocaj, int(self.surface.winId()))", MEDIA)
        self.assertIn("def resizeEvent", MEDIA)

    def test_celozaslonsko_v_obe_smeri(self):
        self.assertIn('("FULLSCREEN_ON", "FULLSCREEN_OFF")', MEDIA)
        self.assertIn('self._command("exitfullscreen")', MEDIA)

    def test_drm_storitve_ostanejo_v_safeer_os(self):
        self.assertIn("if self.webview2_media.uporablja_drm:", APP)
        self.assertIn('return {"predvajalnik": True}', APP)
        self.assertIn("if (r && r.predvajalnik) return;", OS_JS)
        # Storitev ima stalen profil (prijava ostane), zacasne seje se se vedno pobrisejo.
        self.assertIn('"SafeerDRMProfil"', MEDIA)
        self.assertIn('args.append("--storitev=1")', MEDIA)

    def test_splet_preda_zasciten_video(self):
        self.assertIn("navigator.requestMediaKeySystemAccess = function", POLICY)
        self.assertIn("preveriEme", POLICY)

    def test_brez_omembe_pogona_v_vmesniku(self):
        self.assertNotIn("Safeer Media · WebView2", MEDIA)


if __name__ == "__main__":
    unittest.main()
