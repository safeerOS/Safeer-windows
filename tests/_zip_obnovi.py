"""Znova zgradi windows/launcher_go/safeer-os-windows.zip iz TRENUTNEGA delovnega drevesa
(core/, windows/, assets/), namesto delnega popravka dveh datotek. Tako zip vsebuje vse
popravke, ki so ze v izvorni kodi (npr. os_app.py vrni_odgovor), ne le tistih dveh, ki smo
jih rocno popravili prej."""
import os
import zipfile

ROOT = os.path.abspath(".")
ZIP_POT = os.path.join(ROOT, "windows", "launcher_go", "safeer-os-windows.zip")
BACKUP = ZIP_POT + ".pred-polno-obnovo.bak"

VKLJUCI = ["core", "windows", "assets"]
IZKLJUCI_MAPE = {"__pycache__", "launcher_go", "build", "dist", ".mypy_cache", ".pytest_cache"}
IZKLJUCI_PRIPONE = {".pyc", ".pyo", ".exe", ".zip", ".bak"}


def naj_gre_v_zip(pot_rel: str) -> bool:
    deli = pot_rel.replace(os.sep, "/").split("/")
    if any(d in IZKLJUCI_MAPE for d in deli):
        return False
    _, ext = os.path.splitext(pot_rel)
    if ext.lower() in IZKLJUCI_PRIPONE:
        return False
    return True


if os.path.exists(ZIP_POT) and not os.path.exists(BACKUP):
    os.replace(ZIP_POT, BACKUP)
    print("varnostna kopija:", BACKUP)

steto = 0
with zipfile.ZipFile(ZIP_POT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for mapa in VKLJUCI:
        baza = os.path.join(ROOT, mapa)
        if not os.path.isdir(baza):
            continue
        for dirpath, dirnames, filenames in os.walk(baza):
            dirnames[:] = [d for d in dirnames if d not in IZKLJUCI_MAPE]
            for ime in filenames:
                polna = os.path.join(dirpath, ime)
                rel = os.path.relpath(polna, ROOT)
                if not naj_gre_v_zip(rel):
                    continue
                zf.write(polna, rel.replace(os.sep, "/"))
                steto += 1

print("novih vnosov v zipu:", steto)
print("velikost zipa:", os.path.getsize(ZIP_POT), "bajtov")
