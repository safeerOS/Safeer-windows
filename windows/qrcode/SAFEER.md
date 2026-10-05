# qrcode (priložena knjižnica)

Knjižnica [python-qrcode](https://github.com/lincolnloop/python-qrcode) različice **7.4.2**, licenca BSD (datoteka
`LICENSE` v tej mapi; besedilo je iz uradnega paketa `qrcode` na PyPI). Safeer Link z njo nariše kodo QR za povezavo
nove naprave (`core/link_hub.py`, `qr_svg`) – kot SVG, brez dodatnih knjižnic.

Priložena je zato, da koda QR ne zavisi od tega, kaj je nameščeno v uporabnikovem Pythonu.

## Spremembe glede na izvirnik

Datoteke so enake izvirniku 7.4.2, razen:

- `main.py`: `Literal` se uvozi iz `typing` (ne iz `typing_extensions`); `PyPNGImage` (modul `png` iz paketa
  `pypng`) se uvozi šele v `make_image`, kadar kdo res zahteva sliko PNG in knjižnice PIL ni.
- `image/svg.py`: `Literal` se uvozi iz `typing`.

Razlog (izmerjeno 5. 10. 2026): izvirnik ob `import qrcode` zahteva modul `png`, ki ga Safeer OS ne namesti. Uvoz
je padel (`No module named 'png'`), `qr_svg` je vrnil prazen niz in okno »Poveži naprave« je bilo brez kode QR.
