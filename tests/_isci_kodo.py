import subprocess
vzorci = ["kod", "6-mest", "sestm", "parjenj", "poveziKod", "vnesiKodo", "pairing_code", "code_pair"]
poti = ["assets/os/os.js", "assets/os/index.html", "assets/os/os.css", "assets/os/besedila.js",
        "windows/safeer_windows/os_app.py", "windows/safeer_windows/control_backend.py",
        "core/link_hub.py", "core/link_hub_streznik.py"]
for pot in poti:
    try:
        vsebina = open(pot, encoding="utf-8", errors="ignore").read()
    except FileNotFoundError:
        print(pot, "MANJKA")
        continue
    zadetki = [v for v in vzorci if v.lower() in vsebina.lower()]
    print(pot, "->", zadetki if zadetki else "brez zadetkov")
