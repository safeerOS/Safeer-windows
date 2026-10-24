"""Odpiranje lastnih baz SQLite (Knjiznica, Sporocila) z enakimi varnimi nastavitvami - revizija stabilnosti 20. 10. 2026.

Revizija: 8 klicev sqlite3.connect, nobeden z WAL. Sporocila odpreta isto bazo z dvema povezavama (storitev in graf
identitet); v privzetem nacinu (rollback journal) dolgo branje ene zadrzi pisanje druge, po prekinjenem zapisu pa
vroc dnevnik (-journal) obnovi sele naslednji pisec.

  * journal_mode=WAL: bralci in pisec se ne cakajo, prekinitev ne pokvari baze;
  * synchronous=NORMAL (v WAL varno ob sesutju programa; ob izpadu elektrike se izgubi kvecjemu zadnji zapis);
  * busy_timeout izrecno ROK_S (enako kot privzeti timeout modula sqlite3, a zapisano in preverjeno).

Tuji kljuci (foreign_keys) ostanejo, kot so bili: vklop bi spremenil obnasanje obstojecih shem (ON DELETE CASCADE).
Tuje baze (piskotki Firefoxa, zaznamki) se odpirajo samo za branje in jih ta modul ne spreminja.
"""
from __future__ import annotations

import sqlite3

ROK_S = 5.0


def odpri(pot, **kwargs) -> sqlite3.Connection:
    kwargs.setdefault("timeout", ROK_S)
    baza = sqlite3.connect(str(pot), **kwargs)
    try:
        baza.execute("PRAGMA busy_timeout=%d" % int(kwargs["timeout"] * 1000))
        baza.execute("PRAGMA journal_mode=WAL")
        baza.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        # Baza na datotecnem sistemu brez deljenega pomnilnika (omrezni disk): ostane v privzetem nacinu.
        pass
    return baza
