Vzrok:
V `windows/safeer_windows/navidezni_zaslon.py` in `core/link_hub_streznik.py` je manjkala podpora za prenos zaslona prek releja (Global Link). `navidezni_zaslon.py` ni vrnil `"relay": bool(prek_huba)` v odgovoru `zacni_sejo()`. Poleg tega ni imel metod `caka()`, `prevzemi()` in `_vzemi_prevzetega()`, ki bi omogočale sprejem povezave od Huba. `core/link_hub_streznik.py` ni imel poti `POT_NAMIZJE = "/cast/desktop"` in metode `_namizje()`, ki bi povezavo nadgradila na `safeer-desktop` in jo predala seji zaslona prek metode `prevzemi()`.

Kaj je spremenjeno:
1. V `core/link_hub_streznik.py` dodana pot `POT_NAMIZJE = "/cast/desktop"` in metoda `_namizje()`, ki preveri žeton in povezavo nadgradi (101 Switching Protocols) ter jo preda `zaslon.prevzemi()`. V `do_GET()` dodano usmerjanje za `POT_NAMIZJE`.
2. V `windows/safeer_windows/control_backend.py` v `_obdelaj_nadzorni_ukaz` pri `screen.start` dodano posredovanje `prek_huba=bool(params.get("relay"))` pri klicu `zacni_sejo()`. Hubu se prav tako nastavi `streznik.zaslon = lambda: self.navidezni_zaslon`.
3. V `windows/safeer_windows/navidezni_zaslon.py` dodan parameter `prek_huba` v `zacni_sejo()`, ki v glavi vrne `"relay": bool(prek_huba)`. Dodane metode `caka()`, `prevzemi()` in `_vzemi_prevzetega()`. Spremenjena metoda `_sprejmi()`, da povezavo najprej preveri prek `_vzemi_prevzetega()`.
4. V `tests/test_link_hub_zaslon.py` dodan preizkus `test_odgovor_screen_start_relay_in_pot_desktop`.
5. V `windows/tests/test_os_windows.py` dodan preizkus `test_dohodni_ukaz_screen_start_relay`.

Ukazi in izpis preizkusov:
Pred:
```
E           KeyError: 'relay'
...
E       AssertionError: 404 != 101
```

Po:
```
PYTHONPATH=windows python3 -m pytest -q -p no:cacheprovider windows/tests/test_os_windows.py tests/test_link_hub_zaslon.py tests/test_link_zaslon_sredisce.py
........................................................................ [ 47%]
.................................................................sssssss [ 94%]
ssssssss                                                                 [100%]
137 passed, 15 skipped in 6.42s
```

Kaj ostane za rocni preizkus:
Telefon na mobilnih podatkih -> testni PC Windows.

KONEC.
