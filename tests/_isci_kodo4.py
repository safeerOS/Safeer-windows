import re
def izpis(pot, vzorec, kontekst=8):
    try:
        vrstice = open(pot, encoding="utf-8", errors="ignore").read().splitlines()
    except FileNotFoundError:
        print(pot, "MANJKA")
        return
    for i, v in enumerate(vrstice):
        if re.search(vzorec, v, re.IGNORECASE):
            print(f"--- {pot}:{i+1}")
            for j in range(max(0, i-2), min(len(vrstice), i+4)):
                print(f"{j+1}: {vrstice[j]}")

izpis("windows/safeer_windows/control_window.py", "koda|prijava|nacin|pair")
