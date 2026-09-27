"""Kriptografija Safeer Linka brez obveznega zunanjega programa `openssl`.

Windows `openssl` privzeto nima, zato racunalnik z Windows prej ni mogel ustvariti svoje
identitete v krogu zaupanja, podpisati prijave pri hubu, preveriti podpisa ali zagnati TLS
streznika za datoteke. Ta modul uporabi knjiznico `cryptography` (na Windows je namescena
skupaj s Safeer OS), `openssl` pa samo kot rezervo, ce knjiznice ni (npr. star Linux).

Oblike ostanejo tocno enake kot doslej in kot na Androidu (HubTls):
  * kljuc: EC P-256, PEM PKCS#8 brez gesla (kot `openssl req -newkey ec -nodes`),
  * potrdilo: samopodpisano X.509, CN "Safeer Control <ime>", 3650 dni,
  * javni kljuc: SubjectPublicKeyInfo DER,
  * podpis: SHA256withECDSA v zapisu DER,
  * ECDH: surova skupna skrivnost P-256 (x koordinata, 32 bajtov) - enako kot `openssl pkeyutl -derive`.
Zasebni kljuc ne zapusti datoteke na disku in se nikoli ne zapise v dnevnik.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import tempfile
from typing import Optional


def _crypto():
    """Vrne module knjiznice cryptography ali None, ce je ni."""
    try:
        from cryptography import x509  # type: ignore
        from cryptography.hazmat.primitives import hashes, serialization  # type: ignore
        from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore
        from cryptography.x509.oid import NameOID  # type: ignore
        return x509, hashes, serialization, ec, NameOID
    except Exception:
        return None


def _nalozi_zasebni(pot_kljuca: str):
    c = _crypto()
    if c is None:
        return None
    _x509, _hashes, serialization, _ec, _oid = c
    with open(pot_kljuca, "rb") as d:
        return serialization.load_pem_private_key(d.read(), password=None)


def ustvari_kljuc_in_potrdilo(pot_kljuca: str, pot_potrdila: str, ime: str) -> None:
    """Nov EC P-256 kljuc in samopodpisano potrdilo (ce se ne obstajata)."""
    c = _crypto()
    if c is None:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-days", "3650", "-subj", f"/CN=Safeer Control {ime}",
                        "-keyout", pot_kljuca, "-out", pot_potrdila], check=True, capture_output=True)
        return
    x509, hashes, serialization, ec, NameOID = c
    kljuc = ec.generate_private_key(ec.SECP256R1())
    ime_x509 = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Safeer Control {ime}")])
    zdaj = datetime.datetime.now(datetime.timezone.utc)
    potrdilo = (x509.CertificateBuilder()
                .subject_name(ime_x509).issuer_name(ime_x509)
                .public_key(kljuc.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(zdaj - datetime.timedelta(minutes=5))
                .not_valid_after(zdaj + datetime.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(kljuc, hashes.SHA256()))
    pem_kljuca = kljuc.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
    # Kljuc zapisemo z omejenimi pravicami ze ob nastanku (ne sele po zapisu).
    fd = os.open(pot_kljuca, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as d:
        d.write(pem_kljuca)
    with open(pot_potrdila, "wb") as d:
        d.write(potrdilo.public_bytes(serialization.Encoding.PEM))


def javni_kljuc_der(pot_kljuca: str) -> bytes:
    """SubjectPublicKeyInfo DER javnega kljuca za dano zasebno datoteko."""
    zasebni = _nalozi_zasebni(pot_kljuca)
    if zasebni is None:
        return subprocess.run(["openssl", "pkey", "-in", pot_kljuca, "-pubout", "-outform", "DER"],
                              check=True, capture_output=True).stdout
    _x509, _h, serialization, _ec, _o = _crypto()
    return zasebni.public_key().public_bytes(serialization.Encoding.DER,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)


def podpisi(pot_kljuca: str, podatki: bytes) -> bytes:
    """SHA256withECDSA podpis (DER)."""
    zasebni = _nalozi_zasebni(pot_kljuca)
    if zasebni is None:
        return subprocess.run(["openssl", "dgst", "-sha256", "-sign", pot_kljuca],
                              input=podatki, check=True, capture_output=True).stdout
    _x509, hashes, _s, ec, _o = _crypto()
    return zasebni.sign(podatki, ec.ECDSA(hashes.SHA256()))


def preveri(spki_der: bytes, podatki: bytes, podpis_der: bytes) -> bool:
    """Ali je podpis veljaven za te podatke in ta javni kljuc? Vsaka napaka pomeni False."""
    c = _crypto()
    if c is not None:
        try:
            _x509, hashes, serialization, ec, _o = c
            javni = serialization.load_der_public_key(spki_der)
            if not isinstance(javni, ec.EllipticCurvePublicKey):
                return False
            javni.verify(podpis_der, podatki, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False
    mapa = tempfile.mkdtemp(prefix="safeer-podpis-")
    try:
        pot_k, pot_p = os.path.join(mapa, "kljuc.der"), os.path.join(mapa, "podpis.bin")
        with open(pot_k, "wb") as d:
            d.write(spki_der)
        with open(pot_p, "wb") as d:
            d.write(podpis_der)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pot_k, "-keyform", "DER",
                            "-signature", pot_p], input=podatki, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False
    finally:
        import shutil
        shutil.rmtree(mapa, ignore_errors=True)


def ecdh(pot_kljuca: str, tuj_spki_der: bytes) -> bytes:
    """Surova ECDH P-256 skupna skrivnost (32 bajtov), simetricna: A.ecdh(B) == B.ecdh(A)."""
    zasebni = _nalozi_zasebni(pot_kljuca)
    if zasebni is not None:
        _x509, _h, serialization, ec, _o = _crypto()
        tuj = serialization.load_der_public_key(tuj_spki_der)
        return zasebni.exchange(ec.ECDH(), tuj)
    mapa = tempfile.mkdtemp(prefix="safeer-ecdh-")
    try:
        pot_t = os.path.join(mapa, "tuj.der")
        with open(pot_t, "wb") as d:
            d.write(tuj_spki_der)
        r = subprocess.run(["openssl", "pkeyutl", "-derive", "-inkey", pot_kljuca, "-peerkey", pot_t,
                            "-peerform", "DER"], capture_output=True)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("ECDH ni uspel")
        return r.stdout
    finally:
        import shutil
        shutil.rmtree(mapa, ignore_errors=True)


def zaledje() -> str:
    """'cryptography' ali 'openssl' - za diagnostiko (Nastavitve / dnevnik)."""
    return "cryptography" if _crypto() is not None else "openssl"
