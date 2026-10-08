"""»Ves disk« in deljene mape na Windows ne smejo izdati AppData (kljuci/zetoni programov), sistemskih map,
registrskih panjev (zunanji pregled, Windows razlicica Linux tocke 1, 8. 10. 2026) in omreznih (UNC) poti (F2)."""
import os
import tempfile
import unittest

from core import link_datoteke as ld


class ObcutljivePoti(unittest.TestCase):
    def test_appdata_in_sistemske_so_obcutljive(self):
        for p in (r"C:\Users\uporabnik\AppData\Roaming\Safeer\key.pem",
                  r"C:\Users\uporabnik\AppData\Local\Google\Chrome\User Data\Default\Cookies",
                  "C:/Users/uporabnik/Application Data/x", r"D:\Local Settings\Temp\a",
                  r"C:\Windows\System32\config\SAM", "C:/Program Files/x", r"C:\Program Files (x86)\y",
                  r"C:\ProgramData\secret", r"C:\$Recycle.Bin\S-1-5\f", "C:/System Volume Information/z",
                  r"C:\Recovery\a", r"C:\Users\uporabnik\NTUSER.DAT", "C:/pagefile.sys",
                  "/proc/1/environ", "/etc/shadow", "/root/.ssh/id_rsa"):
            self.assertTrue(ld._obcutljiva(p), p)

    def test_unc_in_naprava_poti_so_obcutljive(self):
        """F2: omrezna (UNC) in razsirjena/naprava pot obideta preverjanje po prvi komponenti - zato jih zavrnemo v celoti."""
        for p in (r"\\localhost\C$\Windows\System32\config\SAM", r"\\host\share\Windows\System32\config\SYSTEM",
                  r"\\192.168.0.5\javno\film.mkv", r"\\?\C:\Windows\System32\config\SAM", r"\\.\C:\Windows",
                  "//attacker/share/x", r"\\?\UNC\server\share\x"):
            self.assertTrue(ld._obcutljiva(p), p)
            self.assertTrue(ld._je_unc(p), p)

    def test_navadne_poti_niso_obcutljive(self):
        for p in (r"C:\Users\uporabnik\Documents\film.mkv", "C:/Users/uporabnik/Music/pesem.mp3",
                  r"D:\Filmi\a.mkv", "/home/uporabnik/Videos/x.mp4", r"C:\Users\uporabnik\Desktop\slika.jpg",
                  r"E:\AppDataBackup\ni-skrita.txt", r"C:\Users\uporabnik\Documents\Program Files Notes.txt",
                  # komponenta z imenom sistemske mape globlje v poti NI sistemska mapa (brez prevec-blokiranja):
                  r"C:\Users\uporabnik\Music\Run\Time.flac", "/home/uporabnik/Videos/dev/posnetek.mp4",
                  r"D:\Glasba\System Of A Down\toxicity.mp3", "/home/uporabnik/Music/etc/album/a.mp3"):
            self.assertFalse(ld._obcutljiva(p), p)
            self.assertFalse(ld._je_unc(p), p)

    def test_crka_diska_se_ne_steje_kot_komponenta(self):
        self.assertEqual(ld._komponente(r"C:\Windows\x")[0], "windows")
        self.assertEqual(ld._komponente("C:/Users/m/AppData"), ["users", "m", "appdata"])


class DeljenaMapaNeOdpreAppData(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.mapa, "Documents"))
        with open(os.path.join(self.mapa, "Documents", "a.txt"), "w") as f:
            f.write("ok")
        os.makedirs(os.path.join(self.mapa, "AppData", "Roaming", "Safeer"))
        with open(os.path.join(self.mapa, "AppData", "Roaming", "Safeer", "key.txt"), "w") as f:
            f.write("TAJNO")
        self.d = ld.DeljeneMape([self.mapa])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.mapa, ignore_errors=True)

    def test_seznam_ne_pokaze_appdata(self):
        imena = {v["name"] for v in self.d.seznam("share:0:")}
        self.assertIn("Documents", imena)
        self.assertNotIn("AppData", imena)

    def test_razresi_zavrne_pot_v_appdata(self):
        self.assertIsNone(self.d.razresi("share:0:AppData/Roaming/Safeer/key.txt"))
        self.assertIsNone(self.d.razresi("share:0:AppData"))
        # Prava datoteka ostane dosegljiva.
        self.assertIsNotNone(self.d.razresi("share:0:Documents/a.txt"))


class VesDiskZavrneUnc(unittest.TestCase):
    """F2: ko je »ves disk« vklopljen, oznaka disk: z UNC/napravo pot ne razresi (in ne sprozi realpath nad omrezjem)."""

    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        with open(os.path.join(self.mapa, "film.mkv"), "w") as f:
            f.write("x")
        self.d = ld.DeljeneMape([], ves_disk=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.mapa, ignore_errors=True)

    def test_razresi_zavrne_unc(self):
        for o in (r"disk:\\localhost\C$\Windows\System32\config\SAM", r"disk:\\host\share\Windows\x",
                  r"disk:\\?\C:\Windows\System32\config\SAM", r"disk:\\.\C:\x", "disk://attacker/share/x"):
            self.assertIsNone(self.d.razresi(o), o)

    def test_razresi_dovoli_krajevno_pot(self):
        # Krajevna (ne-UNC) pot se razresi normalno, ko je ves disk vklopljen.
        self.assertIsNotNone(self.d.razresi("disk:" + os.path.join(self.mapa, "film.mkv")))


if __name__ == "__main__":
    unittest.main()
