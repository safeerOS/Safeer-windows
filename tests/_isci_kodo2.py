import re
def izpis(pot, vzorec, kontekst=6):
    try:
        vrstice = open(pot, encoding="utf-8", errors="ignore").read().splitlines()
    except FileNotFoundError:
        print(pot, "MANJKA")
        return
    for i, v in enumerate(vrstice):
        if re.search(vzorec, v, re.IGNORECASE):
            print(f"--- {pot}:{i+1}")
            for j in range(max(0, i-2), min(len(vrstice), i+3)):
                print(f"{j+1}: {vrstice[j]}")

izpis("assets/os/os.js", "kod")
izpis("assets/os/besedila.js", "kod|6.?mest")
izpis("windows/safeer_windows/control_backend.py", "kod")
izpis("core/link_hub_streznik.py", "kod")
