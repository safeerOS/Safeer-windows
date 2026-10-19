# Safeer OS za Windows 1.0.49

**Kazalec miške je na tablici, telefonu in televizorju viden – in se premika takoj.** Slika zaslona kazalca ne vsebuje (Windows ga pri zajemu ne nariše). Računalnik zdaj pošlje položaj in obliko kazalca vsakič, ko se spremenita, naprava pa ga nariše sama. V domačem omrežju je od premika do novega položaja izmerjeno okoli 4 ms (mediana 30 meritev) namesto okoli 43 ms, kolikor potrebuje slika.

**Zaslon lahko prevzame druga naprava – brez izmenjevanja.** Zaslon gleda ena naprava naenkrat. Ko ga odpreš na drugi, ga dobi ta, prejšnja pa izve, katera ga zdaj gleda, in se ne poveže znova. Prej sta se napravi vsako sekundo izmenjevali. Ukaz »ustavi« ustavi samo sejo naprave, ki zaslon res gleda.

- Za izris kazalca in obvestilo o prevzemu potrebuje naprava Safeer OS 0.5.76; starejše naprave delujejo kot prej.
