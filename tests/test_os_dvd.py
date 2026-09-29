"""DVD brez zaščite (core/os_dvd.py): prepoznava slike ISO in mape VIDEO_TS, naslov dvd:// za GStreamer
(Linux) in LibVLC (Windows: dvd:///C:/..., dvd:///D:/) ter optični pogoni prek Win32 (lažen kernel32)."""
import ctypes
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOREN)

from core import os_dvd  # noqa: E402


def zapis(ime: bytes, sektor: int, mapa: bool) -> bytes:
    z = bytearray(33 + len(ime) + (0 if len(ime) % 2 else 1))
    z[0] = len(z)
    z[2:6] = sektor.to_bytes(4, "little")
    z[10:14] = (2048).to_bytes(4, "little")
    z[25] = 2 if mapa else 0
    z[32] = len(ime)
    z[33:33 + len(ime)] = ime
    return bytes(z)


def iso(pot: str, imena) -> None:
    slika = bytearray(2048 * 24)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[156:190] = zapis(b"\x00", 20, True)[:34]
    slika[16 * 2048:17 * 2048] = pvd
    koren = b"".join(zapis(i, 21, True) for i in [b"\x00", b"\x01"] + list(imena))
    slika[20 * 2048:20 * 2048 + len(koren)] = koren
    with open(pot, "wb") as d:
        d.write(slika)


class Dvd(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_iso_z_video_ts(self):
        film = os.path.join(self.d, "Moj_film.iso")
        iso(film, [b"AUDIO_TS", b"VIDEO_TS"])
        podatki = os.path.join(self.d, "podatki.iso")
        iso(podatki, [b"DOKUMENTI"])
        self.assertTrue(os_dvd.je_dvd(film))
        self.assertFalse(os_dvd.je_dvd(podatki))
        self.assertEqual(os_dvd.naslov(film), "Moj film")
        with mock.patch.object(os_dvd, "_windows", lambda: False):
            self.assertEqual(os_dvd.uri(film), "dvd://" + os.path.realpath(film))
        with self.assertRaises(ValueError):
            os_dvd.uri(self.d)                               # mapa brez VIDEO_TS ni DVD

    def test_zascito_css_prepoznamo(self):
        def disk(ime, zastavica):
            mapa = os.path.join(self.d, ime, "VIDEO_TS")
            os.makedirs(mapa)
            open(os.path.join(mapa, "VIDEO_TS.IFO"), "wb").close()
            sektor = bytearray(2048)
            sektor[0:4] = b"\x00\x00\x01\xba"
            sektor[14:18] = b"\x00\x00\x01\xe0"
            sektor[0x14] = zastavica
            with open(os.path.join(mapa, "VTS_01_1.VOB"), "wb") as d:
                d.write(bytes(sektor) * 64)
            return os.path.join(self.d, ime)
        self.assertFalse(os_dvd.je_zasciten(disk("prost", 0x80)))
        self.assertTrue(os_dvd.je_zasciten(disk("zasciten", 0x90)))
        self.assertTrue(os_dvd.je_zasciten("dvd://" + os.path.join(self.d, "zasciten")))
        self.assertIsNone(os_dvd.je_zasciten(self.d))

    def test_mapa_video_ts(self):
        disk = os.path.join(self.d, "Počitnice 2003")
        os.makedirs(os.path.join(disk, "VIDEO_TS"))
        open(os.path.join(disk, "VIDEO_TS", "VIDEO_TS.IFO"), "wb").close()
        ifo = os.path.join(disk, "VIDEO_TS", "VIDEO_TS.IFO")
        self.assertTrue(os_dvd.je_dvd(ifo))
        self.assertEqual(os_dvd.naslov(ifo), "Počitnice 2003")
        with mock.patch.object(os_dvd, "_windows", lambda: False):
            self.assertEqual(os_dvd.uri(ifo), "dvd://" + os.path.realpath(disk))

    def test_naslovi_vlc_za_windows(self):
        film = os.path.join(self.d, "Moj film #1.iso")
        iso(film, [b"VIDEO_TS"])
        with mock.patch.object(os_dvd, "_windows", lambda: True):
            # Poševnice naprej, odstotno kodirano kot vlc_path2uri (presledek, #).
            self.assertEqual(os_dvd.uri(film), "dvd://" + os.path.realpath(film).replace(" ", "%20").replace("#", "%23"))
            self.assertEqual(os_dvd.uri("D:\\"), "dvd:///D:/")
            self.assertEqual(os_dvd.uri("e:"), "dvd:///E:/")
        self.assertEqual(os_dvd._vlc_uri("C:\\Filmi\\Moj film.iso"), "dvd:///C:/Filmi/Moj%20film.iso")

    def test_pogoni_windows(self):
        disk = os.path.join(self.d, "disk")
        os.makedirs(os.path.join(disk, "VIDEO_TS"))
        open(os.path.join(disk, "VIDEO_TS", "VIDEO_TS.IFO"), "wb").close()

        class Kernel32:
            def GetLogicalDrives(self):  # noqa: N802
                return (1 << 2) | (1 << 3) | (1 << 4)       # C:, D:, E:

            def SetErrorMode(self, _m):  # noqa: N802
                return 0

            def GetDriveTypeW(self, koren):  # noqa: N802
                return 3 if koren.value == "C:\\" else os_dvd.DRIVE_CDROM

            def GetVolumeInformationW(self, koren, oznaka, *_a):  # noqa: N802
                if koren.value == "D:\\":
                    oznaka.value = "MOJ_FILM"
                    return 1
                return 0                                       # E: prazen pogon

        prave = {"D:\\": disk}
        with mock.patch.object(ctypes, "windll", mock.Mock(kernel32=Kernel32()), create=True), \
                mock.patch.object(os_dvd, "_windows", lambda: True), \
                mock.patch.object(os_dvd, "_mapa_video_ts", lambda pot: prave.get(pot)):
            pogoni = os_dvd.pogoni()
        self.assertEqual(pogoni, [{"naprava": "D:\\", "vstavljen": True, "ime": "MOJ FILM"},
                                  {"naprava": "E:\\", "vstavljen": False, "ime": "DVD"}])

    def test_pogoni_brez_windows_api_so_prazni(self):
        with mock.patch.object(os_dvd, "_windows", lambda: True), \
                mock.patch.object(os_dvd, "_pogoni_windows", mock.Mock(side_effect=OSError)):
            self.assertEqual(os_dvd.pogoni(), [])


if __name__ == "__main__":
    unittest.main()
