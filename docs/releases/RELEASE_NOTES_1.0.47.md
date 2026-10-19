# Safeer OS za Windows 1.0.47

**Oddaljeni zaslon dvakrat bolj tekoč.** Ko ta računalnik uporabljaš z druge naprave (Safeer Link, doma), Windows zaslon zdaj zajema prek DXGI (tako kot sistemska oddaljena namizja), sliko pa stisne strojni kodirnik grafične kartice (Intel Quick Sync, NVIDIA, AMD). Izmerjeno od testnega računalnika (i5-4590, Intel HD 4600) do Safeer Controla na Linuxu: prej 29 slik na sekundo, zdaj 59, slika vsakih 17 ms.

- **Deluje tudi ob ugasnjenem monitorju:** takrat Windows zaslona ne riše, zato Safeer sam preklopi na rezervni zajem (okoli 27 slik na sekundo).
- Knjižnica za hitri zajem (`dxcam`, MIT) se namesti sama; brez nje oddaljeni zaslon deluje kot prej (do 30 slik na sekundo).
- Namestitev knjižnic ne čaka več, da potrdiš obvestilo.

Za 60 slik na sekundo na Linuxu potrebuješ Safeer Control 2.1.72 (Safeer za Linux 1.0.116).
