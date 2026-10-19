# Safeer OS za Windows 1.0.48

**Oddaljeni zaslon se odziva skoraj dvakrat hitreje.** Od premika miške na drugi napravi do spremenjene slike nazaj na njej zdaj mine okoli 43 ms (prej okoli 66 ms). Izmerjeno od testnega računalnika (i5-4590, Intel HD 4600) do Safeer Controla na Linuxu, 20 meritev: najmanj 33 ms; slika ostaja pri 60 slikah na sekundo.

- Zaslon se zajame takoj, ko ga Windows nariše, ne v stalnem ritmu.
- Priprava slike za kodirnik traja okoli 2 ms namesto okoli 10 ms.
- Glava seje pove, da je vsak okvir cela slika: novejši Safeer OS na televizorju, tablici in telefonu jo bo lahko izrisal brez čakanja.
