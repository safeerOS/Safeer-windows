# Pravila za AI pomocnike (Claude, Codex, Antigravity …) v tem repozitoriju

Skupna pravila vseh repozitorijev Safeer; najpopolnejsa razlicica je `AGENTS.md` v safeerOS/Safeer-linux.
Vsako od spodnjih pravil izhaja iz napake, ki je ze bila narejena.

## Zasebnost
- Nikoli v repo, commit, PR ali opombe izdaje: ime lastnika, domaca pot, uporabnisko ime, ime gostitelja, MAC,
  e-naslovi, posnetki zaslona naprav. V besedilu pisi »lastnik«.
- Gesla, zetoni in kljuci nikoli v repo; podpisni kljuci ostanejo na lastnikovem racunalniku.
- Tudi zgrajeni paketi (APK, exe, deb) ne smejo vsebovati domacih poti ali imen (Go: `-trimpath`; preveri s `strings`).

## Git in izdaje
- Avtor commitov je ekipa: `Safeer <info@safeer.si>`, brez vrstic `Co-Authored-By` ali `Claude-Session`.
- Brez `--force`, brez brisanja oznak in izdaj. Nic se ne objavi brez lastnikovega »da«.
- Pred potiskom nove veje preveri, kaj vse gre ven (`git rev-list <veja> --not <vrhovi iz git ls-remote>`): stevilo
  commitov, avtorje, vsebino. Nikoli ne potiskaj iz starega klona z zgodovino pred ciscenjem (19. 10. 2026: veja
  `obnova-zavihka` je v safeerOS odnesla stare commite z imenom lastnika). Nov repozitorij je najprej zaseben.
- Objava sele po neodvisnem pregledu (drug agent ali clovek, ki dela ni naredil) in po pregledu varnostno obcutljive
  kode (posodobitve, dostop naprav, dovoljenja, DNS).

## Varnost kode
- Ce program z visjimi pravicami (root, sistemska storitev, druga aplikacija) uporabi datoteko, ki jo lahko spremeni
  manj privilegiran program, jo mora sam prekopirati in preveriti KOPIJO ali dobiti vsebino neposredno. Preverba pred
  predajo ne zadosca: datoteko lahko zamenja med preverbo in uporabo (neodvisni pregled 19. 10. 2026).
- Po vsaki spremembi gradnje (prevajalnik, povezovalnik, optimizacija) preveri zascite izvorne kode v paketu: pri
  knjiznicah ELF `readelf -lW` -> `GNU_STACK ... RW` brez E (19. 10. 2026: BOLT `--use-gnu-stack` je naredil izvrsljiv
  sklad). Hitrost ni razlog za manj zascite.
- Vsak varnostni popravek ima preizkus, ki brez popravka pade (preveri tako, da popravek zacasno umaknes).

## Meritve in javne trditve
- Odlocamo z izmerjenimi podatki: izmenicne meritve istega dne, enaki pogoji, vsaj tri ponovitve. Stevilka gre v opombe
  ali javno (GitHub, gorvodni projekti) sele, ko je tako izmerjena.

## Zapisnik
- Kar ni delovalo, vodi lastnik izven repozitorija (SAFEER-ZNANJE.md, razdelek ZAPISNIK). Preveri ga pred poskusom in
  dopisi novo napako.
