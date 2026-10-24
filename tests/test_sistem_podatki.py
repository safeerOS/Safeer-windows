"""Diski in podatki o racunalniku (core/sistem_podatki.py): razclenjevanje brez sistema."""
import json
import unittest

from core import sistem_podatki as S

GB = 1024 ** 3
LSBLK = json.dumps({"blockdevices": [
    {"name": "sda", "path": "/dev/sda", "label": None, "size": 512 * GB, "type": "disk", "rm": False, "hotplug": False,
     "mountpoint": None, "fstype": None, "model": "KINGSTON SKC600512G", "children": [
         {"name": "sda1", "path": "/dev/sda1", "label": None, "size": 256 * 1024 ** 2, "type": "part", "mountpoint": "/boot/efi", "fstype": "vfat"},
         {"name": "sda3", "path": "/dev/sda3", "label": "Windows", "size": 350 * GB, "type": "part", "mountpoint": None, "fstype": "ntfs"},
         {"name": "sda4", "path": "/dev/sda4", "label": "Recovery", "size": GB, "type": "part", "mountpoint": None, "fstype": "ntfs"},
         {"name": "sda5", "path": "/dev/sda5", "label": None, "size": 157 * GB, "type": "part", "mountpoint": "/", "fstype": "ext4"},
         {"name": "sda6", "path": "/dev/sda6", "label": None, "size": 8 * GB, "type": "part", "mountpoint": "[SWAP]", "fstype": "swap"}]},
    {"name": "sdb", "path": "/dev/sdb", "size": 1000 * GB, "type": "disk", "model": "ST1000DM003", "children": [
        {"name": "sdb4", "path": "/dev/sdb4", "label": None, "size": 999 * GB, "type": "part", "mountpoint": None, "fstype": "ntfs"}]},
    {"name": "sdc", "path": "/dev/sdc", "size": 64 * GB, "type": "disk", "rm": True, "model": "USB", "children": [
        {"name": "sdc1", "path": "/dev/sdc1", "label": "KLJUC", "size": 64 * GB, "type": "part", "mountpoint": "/media/u/KLJUC", "fstype": "exfat"}]},
    {"name": "loop0", "path": "/dev/loop0", "size": 100 * GB, "type": "loop", "mountpoint": "/snap/x/1", "fstype": "squashfs"}]})


def statvfs(pot):
    return {"/": (155 * GB, 93 * GB), "/media/u/KLJUC": (64 * GB, 2 * GB)}.get(pot)


class Diski(unittest.TestCase):
    def test_lsblk(self):
        d = S.diski_iz_lsblk(LSBLK, statvfs, "/home/u")
        self.assertEqual([x["naprava"] for x in d], ["/dev/sda5", "/dev/sdc1", "/dev/sdb4", "/dev/sda3"])
        sistem = d[0]
        self.assertTrue(sistem["sistem"] and sistem["priklopljen"])
        self.assertEqual((sistem["velikost"], sistem["prosto"]), (155 * GB, 93 * GB))
        self.assertEqual(sistem["model"], "KINGSTON SKC600512G")
        self.assertFalse(sistem["malo_prostora"])
        usb = d[1]
        self.assertTrue(usb["odstranljiv"] and usb["malo_prostora"])          # 2 GB < 5 GB
        hdd = d[2]
        self.assertFalse(hdd["priklopljen"])
        self.assertNotIn("prosto", hdd)
        self.assertEqual(hdd["model"], "ST1000DM003")

    def test_smeti(self):
        self.assertEqual(S.diski_iz_lsblk("ni json", statvfs), [])
        self.assertEqual(S.diski_iz_lsblk("{}", statvfs), [])

    def test_malo_prostora(self):
        self.assertTrue(S.malo_prostora(4 * GB, 1000 * GB))
        self.assertFalse(S.malo_prostora(39 * GB, 502 * GB))                  # velik disk: 8 % ni malo
        self.assertTrue(S.malo_prostora(10 * GB, 128 * GB))                   # pod 10 % in pod 15 GB
        self.assertFalse(S.malo_prostora(0, 0))


class Podatki(unittest.TestCase):
    def test_os_release(self):
        self.assertEqual(S.os_iz_release('NAME="Linux Mint"\nPRETTY_NAME="Linux Mint 22.3"\n'), "Linux Mint 22.3")
        self.assertEqual(S.os_iz_release('NAME="Debian"\nVERSION="12"\n'), "Debian 12")

    def test_cpuinfo(self):
        self.assertEqual(S.procesor_iz_cpuinfo("processor\t: 0\nmodel name\t: Intel(R)  Core(TM) i5\n"), "Intel(R) Core(TM) i5")
        self.assertEqual(S.procesor_iz_cpuinfo(""), "")

    def test_meminfo(self):
        m = S.pomnilnik_iz_meminfo("MemTotal:       12016000 kB\nMemFree: 1000 kB\nMemAvailable:    7245000 kB\nSwapTotal: 0 kB\n")
        self.assertEqual(m, {"skupaj": 12016000 * 1024, "na_voljo": 7245000 * 1024, "izmenjalni": 0})

    def test_lspci(self):
        izpis = ("00:02.0 VGA compatible controller: Intel Corporation TigerLake-LP GT2 [Iris Xe Graphics] (rev 01)\n"
                 "01:00.0 3D controller: NVIDIA Corporation GA107M (rev a1)\n00:1f.3 Audio device: Intel Corporation\n")
        self.assertEqual(S.graficne_iz_lspci(izpis), ["Intel Corporation TigerLake-LP GT2 [Iris Xe Graphics]",
                                                      "NVIDIA Corporation GA107M"])

    def test_podatki_brez_napake(self):
        p = S.podatki()
        for k in ("sistem", "procesor", "jeder", "pomnilnik", "graficne", "diski", "arhitektura"):
            self.assertIn(k, p)


if __name__ == "__main__":
    unittest.main()
