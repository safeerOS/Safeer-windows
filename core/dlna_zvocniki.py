"""Zvocniki v omrezju (UPnP/DLNA MediaRenderer) za Safeer OS: iskanje, predvajanje, glasnost.

Samo odprti standard UPnP AV, brez vmesnikov proizvajalcev. Prvi osnutek: Codex (ChatGPT) na
Lastnikovem testnem Windows racunalniku, pregledal in popravil Claude.
"""
from __future__ import annotations

import html
import mimetypes
import os
import re
import secrets
import select
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SSDP_GROUP = ("239.255.255.250", 1900)
ST = "urn:schemas-upnp-org:device:MediaRenderer:1"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
DEVICE_NS = "urn:schemas-upnp-org:device-1-0"


class DlnaNapaka(Exception):
    """Napaka UPnP/SOAP zahteve."""


def _xml_text(element: ET.Element, name: str) -> str:
    found = element.find(f".//{{{DEVICE_NS}}}{name}")
    return (found.text or "").strip() if found is not None else ""


def _lokalni_url(base: str, control: str) -> str:
    result = urllib.parse.urljoin(base, control)
    a, b = urllib.parse.urlsplit(base), urllib.parse.urlsplit(result)
    if a.scheme not in ("http", "https") or b.scheme != a.scheme or b.hostname != a.hostname or b.port != a.port:
        raise DlnaNapaka("Kontrolni URL je zunaj gostitelja naprave")
    return result


def razcleni_ssdp(odgovor: bytes | str, izvor_ip: str) -> str | None:
    """Vrne LOCATION samo, če njegov gostitelj ustreza pošiljatelju odgovora."""
    text = odgovor.decode("iso-8859-1", "replace") if isinstance(odgovor, bytes) else odgovor
    headers: dict[str, str] = {}
    for line in text.replace("\r\n", "\n").split("\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    loc = headers.get("location")
    if not loc:
        return None
    try:
        p = urllib.parse.urlsplit(loc)
        if p.scheme not in ("http", "https") or (p.hostname or "").lower() != izvor_ip.lower():
            return None
        return loc
    except ValueError:
        return None


def _get(url: str, limit: int = 262144, timeout: float = 5.0) -> bytes:
    req = urllib.request.Request(url)
    # Redirects are rejected; description URLs must stay on the SSDP responder host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=timeout) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise DlnaNapaka("Opis naprave presega omejitev 256 KB")
        return data


@dataclass
class Zvocnik:
    ime: str
    proizvajalec: str
    model: str
    udn: str
    naslov: str
    opis_url: str
    avtransport_url: str
    rendering_url: str
    connection_url: str | None = None
    formati: set[str] = field(default_factory=set)

    @staticmethod
    def _soap(control: str, service: str, action: str, args: dict[str, str] | None = None) -> ET.Element:
        args = args or {}
        body = ET.Element(f"{{{SOAP_NS}}}Envelope", {f"{{{SOAP_NS}}}encodingStyle": "http://schemas.xmlsoap.org/soap/encoding/"})
        wrapper = ET.SubElement(body, f"{{{SOAP_NS}}}Body")
        call = ET.SubElement(wrapper, f"{{{service}}}{action}")
        for key, value in args.items():
            ET.SubElement(call, key).text = value
        payload = ET.tostring(body, encoding="utf-8", xml_declaration=True)
        req = urllib.request.Request(control, data=payload, method="POST", headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{service}#{action}"',
        })
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a: Any, **kw: Any) -> None:
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=5) as response:
                raw = response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            raw = exc.read(1024 * 1024)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise DlnaNapaka(f"Neveljaven SOAP odgovor: {exc}") from exc
        fault = root.find(f".//{{{SOAP_NS}}}Fault")
        if fault is not None:
            code = fault.findtext(".//{*}errorCode") or "unknown"
            desc = fault.findtext(".//{*}errorDescription") or "UPnP SOAP napaka"
            raise DlnaNapaka(f"UPnP {code}: {desc}")
        return root

    def _av(self, action: str, args: dict[str, str] | None = None) -> ET.Element:
        return self._soap(self.avtransport_url, "urn:schemas-upnp-org:service:AVTransport:1", action, {"InstanceID": "0", **(args or {})})

    def _rc(self, action: str, args: dict[str, str] | None = None) -> ET.Element:
        return self._soap(self.rendering_url, "urn:schemas-upnp-org:service:RenderingControl:1", action, {"InstanceID": "0", **(args or {})})

    def predvajaj(self, url: str, naslov: str = "", izvajalec: str = "", mime: str = "audio/mpeg") -> None:
        metadata = didl_lite(url, naslov, izvajalec, mime)
        self._av("SetAVTransportURI", {"CurrentURI": url, "CurrentURIMetaData": metadata})
        self._av("Play", {"Speed": "1"})

    def premor(self) -> None:
        self._av("Pause")

    def nadaljuj(self) -> None:
        self._av("Play", {"Speed": "1"})

    def ustavi(self) -> None:
        self._av("Stop")

    def stanje(self) -> str:
        root = self._av("GetTransportInfo")
        return root.findtext(".//{*}CurrentTransportState", default="")

    def glasnost(self) -> int:
        root = self._rc("GetVolume", {"Channel": "Master"})
        return int(root.findtext(".//{*}CurrentVolume", default="0"))

    def nastavi_glasnost(self, vrednost: int) -> None:
        self._rc("SetVolume", {"Channel": "Master", "DesiredVolume": str(max(0, min(100, int(vrednost))))})

    def polozaj(self) -> dict[str, str | int]:
        root = self._av("GetPositionInfo")
        result: dict[str, str | int] = {}
        for tag, key in (("RelTime", "RelTime"), ("TrackDuration", "TrackDuration"), ("TrackURI", "TrackURI")):
            value = root.findtext(f".//{{*}}{tag}", default="")
            result[key] = value
            if tag != "TrackURI":
                result[key + "Seconds"] = _cas_v_sekunde(value)
        return result

    def podprti_formati(self) -> set[str]:
        if self.formati or not self.connection_url:
            return self.formati
        root = self._soap(self.connection_url, "urn:schemas-upnp-org:service:ConnectionManager:1", "GetProtocolInfo")
        sink = root.findtext(".//{*}Sink", default="")
        for entry in sink.split(","):
            fields = entry.strip().split(":")
            if len(fields) >= 3:
                self.formati.add(fields[2].lower())
        return self.formati


def didl_lite(url: str, naslov: str, izvajalec: str, mime: str) -> str:
    """DIDL-Lite v obliki, ki jo pricakujejo renderji: privzeti imenski prostor DIDL, predpone dc/upnp."""
    e = lambda t: xml_escape(t or "", {'"': "&quot;"})
    return ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            '<item id="0" parentID="0" restricted="1">'
            f'<dc:title>{e(naslov)}</dc:title><upnp:artist>{e(izvajalec)}</upnp:artist>'
            '<upnp:class>object.item.audioItem.musicTrack</upnp:class>'
            f'<res protocolInfo="http-get:*:{e(mime)}:*">{e(url)}</res></item></DIDL-Lite>')


def _cas_v_sekunde(value: str) -> int:
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + int(float(s))
    except (ValueError, TypeError):
        return 0


def _naprava(opis_url: str, izvor_ip: str) -> Zvocnik | None:
    p = urllib.parse.urlsplit(opis_url)
    if p.hostname != izvor_ip:
        return None
    root = ET.fromstring(_get(opis_url))
    device = root.find(f".//{{{DEVICE_NS}}}device")
    if device is None:
        return None
    udn = _xml_text(device, "UDN")
    services: dict[str, str] = {}
    for service in device.findall(f".//{{{DEVICE_NS}}}service"):
        typ = _xml_text(service, "serviceType")
        control = _xml_text(service, "controlURL")
        if control:
            services[typ] = control
    av = next((v for k, v in services.items() if k.startswith("urn:schemas-upnp-org:service:AVTransport:")), None)
    rc = next((v for k, v in services.items() if k.startswith("urn:schemas-upnp-org:service:RenderingControl:")), None)
    if not (udn and av and rc):
        return None
    urlbase = _xml_text(root, "URLBase") or opis_url
    base_parts = urllib.parse.urlsplit(urlbase)
    if base_parts.hostname != p.hostname or base_parts.scheme != p.scheme:
        raise DlnaNapaka("URLBase je zunaj gostitelja naprave")
    return Zvocnik(_xml_text(device, "friendlyName"), _xml_text(device, "manufacturer"), _xml_text(device, "modelName"), udn, p.hostname or "", opis_url, _lokalni_url(urlbase, av), _lokalni_url(urlbase, rc), next((_lokalni_url(urlbase, v) for k, v in services.items() if k.startswith("urn:schemas-upnp-org:service:ConnectionManager:")), None))


def lokalni_vmesniki() -> list[str]:
    """Domaci IPv4 naslovi te naprave. Na Windows z vec omreznimi vmesniki (VPN, Hyper-V ...) gre
    poizvedba brez vezave pogosto skozi napacen vmesnik in zvocnika ni (izmerjeno 29. 9. 2026)."""
    naslovi: list[str] = []
    try:
        naslovi.append(lan_naslov_za("8.8.8.8"))      # vmesnik privzete poti (brez posiljanja)
    except OSError:
        pass
    try:
        for n in socket.gethostbyname_ex(socket.gethostname())[2]:
            if n not in naslovi:
                naslovi.append(n)
    except OSError:
        pass
    return [n for n in naslovi if n and not n.startswith("127.") and not n.startswith("169.254.")]


def najdi(cas: float = 3.0, vmesnik: str | None = None) -> list[Zvocnik]:
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: " + ST + "\r\n\r\n").encode("ascii")
    devices: dict[str, Zvocnik] = {}
    vmesniki = [vmesnik] if vmesnik else (lokalni_vmesniki() or [""])
    socks: list[socket.socket] = []
    try:
        for v in vmesniki:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            try:
                if v:
                    sock.bind((v, 0))
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(v))
                sock.setblocking(False)
                for _ in range(2):  # UDP se lahko izgubi: dve poizvedbi, kot priporoca UPnP
                    sock.sendto(msg, SSDP_GROUP)
                socks.append(sock)
            except OSError:
                sock.close()
        deadline = time.monotonic() + max(0.0, cas)
        locations: set[tuple[str, str]] = set()
        while socks and time.monotonic() < deadline:
            pripravljeni, _, _ = select.select(socks, [], [], 0.2)
            for sock in pripravljeni:
                try:
                    data, addr = sock.recvfrom(65535)
                except OSError:
                    continue
                location = razcleni_ssdp(data, addr[0])
                if location:
                    locations.add((location, addr[0]))
        for location, host in locations:
            try:
                item = _naprava(location, host)
                if item:
                    devices.setdefault(item.udn, item)
            except (OSError, ET.ParseError, DlnaNapaka, ValueError):
                continue
    finally:
        for sock in socks:
            sock.close()
    return list(devices.values())



def lan_naslov_za(cilj_ip: str) -> str:
    """Izbere lokalni IPv4 naslov za pot do cilja brez pošiljanja paketov."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((cilj_ip, 9))
        return sock.getsockname()[0]
    finally:
        sock.close()


class StreznikDatotek:
    """Začasni HTTP strežnik, ki razkrije samo izbrano datoteko pod skrivnim žetonom."""
    def __init__(self, pot: str | os.PathLike[str], naslov_lan: str):
        self.pot = Path(pot).resolve(strict=True)
        self.naslov_lan = naslov_lan
        self.token = secrets.token_urlsafe(24)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "StreznikDatotek":
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass
            def _serve(self, head: bool) -> None:
                expected = "/" + owner.token + "/" + urllib.parse.quote(owner.pot.name)
                if urllib.parse.urlsplit(self.path).path != expected:
                    self.send_error(404)
                    return
                size = owner.pot.stat().st_size
                start, end, status = 0, size - 1, 200
                range_header = self.headers.get("Range")
                if range_header:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                    if not match or (not match.group(1) and not match.group(2)):
                        self.send_error(416)
                        return
                    if match.group(1):
                        start = int(match.group(1))
                        end = int(match.group(2)) if match.group(2) else size - 1
                    else:
                        suffix = int(match.group(2))
                        start, end = max(0, size - suffix), size - 1
                    if start >= size or end < start:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    end, status = min(end, size - 1), 206
                length = max(0, end - start + 1)
                self.send_response(status)
                self.send_header("Content-Type", mimetypes.guess_type(owner.pot.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("transferMode.dlna.org", "Streaming")
                self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if not head and length:
                    with owner.pot.open("rb") as f:
                        f.seek(start)
                        ostane = length
                        while ostane > 0:  # po kosih: pesmi/filmi ne gredo v celoti v pomnilnik
                            kos = f.read(min(65536, ostane))
                            if not kos:
                                break
                            try:
                                self.wfile.write(kos)
                            except (BrokenPipeError, ConnectionResetError):
                                return  # zvocnik je prekinil (npr. premik) - obicajno
                            ostane -= len(kos)
            def do_GET(self) -> None:
                self._serve(False)
            def do_HEAD(self) -> None:
                self._serve(True)
        self._server = ThreadingHTTPServer((self.naslov_lan, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("StreznikDatotek mora biti v kontekstu with")
        name = urllib.parse.quote(self.pot.name)
        return f"http://{self.naslov_lan}:{self._server.server_port}/{self.token}/{name}"

    def __exit__(self, *_: Any) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None





