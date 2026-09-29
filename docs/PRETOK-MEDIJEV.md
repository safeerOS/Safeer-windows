# Safeer Link: glasba in video z drugih naprav (sproti, brez prenosa)

Uporabnik v predvajalniku odpre glasbo ali video, ki je na drugi napravi v njegovem krogu zaupanja
(računalnik, TV, tablica, telefon). Predvajanje se začne takoj. Nič se ne shrani na disk, previjanje
deluje, celotna pot je šifrirana. Doma teče neposredno po LAN, zunaj doma pa prek Global Linka.

## Pot

1. Seznam gre po Safeer Linku (`files.list` v `control.command`). Odgovor nosi `server` = `{base_url, fp, token}`.
2. Datoteke tečejo neposredno z naprave po HTTPS: potrdilo s pripetim odtisom, žeton **samo v glavi**
   `X-Safeer-Token`, `Range` za previjanje.
3. **Zunaj doma:** naprava vsake datoteke streže tudi na svojem Hubu na poti `/cast/d/<id>`
   (Android tudi `/cast/thumb/<id>`, samo GET/HEAD). Rele link.safeer.si pripelje samo do vrat Huba.
   Potrdilo Huba je isto kot potrdilo strežnika datotek (isti ključ), zato velja isti žeton. Zaupanje prek
   releja je ključ iz kroga: ključ v potrdilu mora biti ključ te naprave. Rele vidi samo šifrirane bajte.

## Po platformah

| | Strežnik (deli) | Odjemalec (predvaja) |
|---|---|---|
| Linux | Control: `core/link_datoteke.py` + Hub `/cast/d/` (`core/link_hub_streznik.py`) | Safeer OS → Medijski center → »Z drugih naprav«. `core/link_pretok.py` (lokalni tok 127.0.0.1) → GStreamer, glasba z vrsto albuma, video v oknu predvajalnika |
| Windows | `control_backend._datoteke_za`: en strežnik za omejen dostop in en za cel disk (prej je bil nov strežnik ob vsakem `files.list`) + Hub `/cast/d/` | Datoteke → naprava → skladba ali video se predvaja takoj. Glasba MP3/FLAC/OGG/WAV teče v strani z vrsto, AAC/M4A in video pa v VLC |
| Android | `DatotekeStreznik` + Hub `/cast/d/` (`HubTokovi`) | `PripetiVir`: najprej LAN, ob napaki isti tok prek releja (`GlobalLink.naslov` + `/cast`) |

## Varnost

- **Lokalni tok** (`link_pretok.LokalniPretok`):
  - posluša samo na 127.0.0.1 in sprejema samo povezave s te naprave;
  - vsak vir ima svojo 128-bitno naključno pot `/m/<hex>`, žeton ne gre nikoli v naslov;
  - naprava lahko predlaga samo naslov v domačem omrežju (zasebni/lokalni IP, ne internet);
  - `mime` iz seznama se uporabi samo v obliki `vrsta/podvrsta`.
- **Odločitev o poti** (neposredno ali rele) velja za isto napravo (naslov + odtis + ključ):
  - neposredna pot zahteva pravi odtis na tem naslovu, zato zunaj doma na istem IP ne dobimo tuje naprave;
  - ključ prek releja preverimo enkrat, nato pripnemo odtis.
- **Žetoni:**
  - veljajo 12 ur od zadnje rabe (tok, ki teče, ne pade), največ 7 dni od izdaje;
  - po polovici roka naprava ob novem seznamu dobi novega, prejšnji velja do svojega roka;
  - monotona ura, primerjava v stalnem času;
  - Windows prekliče žeton za cel disk, ko naprava nima več tega dovoljenja.
- **TLS rokovanje** na Hubu in strežniku datotek teče v delovni niti (`link_tls.RokovanjeVNiti`).
  Prej je ena tiha povezava ustavila sprejemanje vseh drugih.

## Preverjeno (29. 9. 2026)

- **Enotski testi:** `tests/test_link_pretok.py`
  - cela datoteka, previjanje, napačen žeton, tuja naprava na istem naslovu;
  - pot prek releja, več strežnikov na Hubu;
  - tiha povezava ne ustavi strežnika, rok žetona.
- **Linux PC → TV in telefon** (skripta):
  - LAN: 5–9 MB/s;
  - prek releja (neposredni naslov namerno mrtev, kot zunaj doma): 1,3–2,3 MB/s;
  - previjanje (206) deluje; GStreamer prepozna MP3, H.264 in WAV.
- **Safeer OS (Linux), v živo:**
  - video s telefona se predvaja v oknu (previjanje deluje);
  - glasba s telefona se predvaja z vrsto, pod njo je ime naprave;
  - kratek WAV s TV se predvaja.
- **Windows, v živo:**
  - MP3 s telefona v strani z vrsto (Naprej preide na naslednjo);
  - M4A s telefona v VLC.
- **Android (testni telefon), v živo:** OGG z Linux računalnika po LAN prek novega `PripetiVir`.
- **Neodvisen pregled varnosti:** vse ugotovitve so popravljene (glej zgoraj).

## Znane meje

- Klic prek releja z Androida (telefon zunaj doma → računalnik ali TV) je zgrajen po istem vzorcu kot
  obstoječa pot Linka prek releja, v živo pa še ni preizkušen.
- Zunaj doma mora naprava, ki deli, gostiti Hub z Global Linkom (Android vedno, računalnik v načinu mesh).
