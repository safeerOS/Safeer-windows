import os, zipfile
print("na disku obstaja assets/link/index.html:", os.path.exists("assets/link/index.html"))
if os.path.isdir("assets/link"):
    print("vsebina assets/link:", sorted(os.listdir("assets/link")))
else:
    print("mapa assets/link NE OBSTAJA")

zf = zipfile.ZipFile("windows/launcher_go/safeer-os-windows.zip")
imena = [n for n in zf.namelist() if n.startswith("assets/")]
print("assets/ v zipu:", imena)
