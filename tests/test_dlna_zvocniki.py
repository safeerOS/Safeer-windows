import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from core import dlna_zvocniki as dlna

DEVICE = "urn:schemas-upnp-org:device-1-0"
AV = "urn:schemas-upnp-org:service:AVTransport:1"
RC = "urn:schemas-upnp-org:service:RenderingControl:1"
CM = "urn:schemas-upnp-org:service:ConnectionManager:1"
SOAP = dlna.SOAP_NS


class FakeRenderer(BaseHTTPRequestHandler):
    bodies = []
    fault = False

    def log_message(self, *_):
        pass

    def do_GET(self):
        payload = f'''<?xml version="1.0"?><root xmlns="{DEVICE}"><device><friendlyName>Test zvočnik</friendlyName><manufacturer>Open</manufacturer><modelName>Mock</modelName><UDN>uuid:test-1</UDN><serviceList>
        <service><serviceType>{AV}</serviceType><controlURL>control/av</controlURL></service>
        <service><serviceType>{RC}</serviceType><controlURL>/control/rc</controlURL></service>
        <service><serviceType>{CM}</serviceType><controlURL>control/cm</controlURL></service>
        </serviceList></device></root>'''.encode()
        self.send_response(200); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        root = ET.fromstring(data)
        call = next(x for x in root.iter() if x.tag.startswith("{") and x.tag.rsplit("}", 1)[-1] not in ("Envelope", "Body"))
        action = call.tag.rsplit("}", 1)[-1]
        self.__class__.bodies.append((self.path, self.headers.get("SOAPACTION"), data, action))
        if self.__class__.fault:
            inner = '<s:Fault><faultcode>s:Client</faultcode><detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0"><errorCode>701</errorCode><errorDescription>Transition not available</errorDescription></UPnPError></detail></s:Fault>'
            response = f'<s:Envelope xmlns:s="{SOAP}"><s:Body>{inner}</s:Body></s:Envelope>'.encode()
        else:
            output = {"GetTransportInfo": "<CurrentTransportState>PLAYING</CurrentTransportState>", "GetVolume": "<CurrentVolume>42</CurrentVolume>", "GetPositionInfo": "<RelTime>00:01:02</RelTime><TrackDuration>00:03:00</TrackDuration><TrackURI>http://127.0.0.1/song.mp3</TrackURI>", "GetProtocolInfo": "<Sink>http-get:*:audio/mpeg:*,http-get:*:audio/flac:*</Sink>"}.get(action, "")
            service = CM if action == "GetProtocolInfo" else (RC if action in ("GetVolume", "SetVolume") else AV)
            response = f'<s:Envelope xmlns:s="{SOAP}"><s:Body><u:{action}Response xmlns:u="{service}">{output}</u:{action}Response></s:Body></s:Envelope>'.encode()
        self.send_response(200); self.send_header("Content-Length", str(len(response))); self.end_headers(); self.wfile.write(response)


class DlnaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeRenderer.bodies = []; FakeRenderer.fault = False
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRenderer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/device.xml"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        FakeRenderer.bodies = []; FakeRenderer.fault = False

    def speaker(self):
        return dlna._naprava(self.base, "127.0.0.1")

    def test_parse_discovery_and_url_resolution(self):
        z = self.speaker()
        self.assertEqual((z.ime, z.proizvajalec, z.model, z.udn), ("Test zvočnik", "Open", "Mock", "uuid:test-1"))
        self.assertEqual(z.avtransport_url, f"http://127.0.0.1:{self.server.server_port}/control/av")
        self.assertEqual(z.rendering_url, f"http://127.0.0.1:{self.server.server_port}/control/rc")
        self.assertEqual(z.podprti_formati(), {"audio/mpeg", "audio/flac"})

    def test_ssdp_response_validation(self):
        sample = "HTTP/1.1 200 OK\r\nlocation: http://192.0.2.4:80/desc.xml\r\nST: test\r\n\r\n"
        self.assertEqual(dlna.razcleni_ssdp(sample, "192.0.2.4"), "http://192.0.2.4:80/desc.xml")
        self.assertIsNone(dlna.razcleni_ssdp(sample, "192.0.2.5"))
        self.assertIsNone(dlna.razcleni_ssdp("HTTP/1.1 200 OK\r\nST: test\r\n", "192.0.2.4"))

    def test_every_soap_action_and_didl_escaping(self):
        z = self.speaker()
        title = 'Čaj & <kava> "okus"'
        z.predvajaj("http://127.0.0.1/song?a=1&b=2", title, "Izvajalec & <x>")
        z.premor(); z.nadaljuj(); z.ustavi()
        self.assertEqual(z.stanje(), "PLAYING")
        self.assertEqual(z.glasnost(), 42)
        z.nastavi_glasnost(140); z.nastavi_glasnost(-3)
        self.assertEqual(z.polozaj(), {"RelTime": "00:01:02", "RelTimeSeconds": 62, "TrackDuration": "00:03:00", "TrackDurationSeconds": 180, "TrackURI": "http://127.0.0.1/song.mp3"})
        actions = [x[3] for x in FakeRenderer.bodies]
        self.assertEqual(actions, ["SetAVTransportURI", "Play", "Pause", "Play", "Stop", "GetTransportInfo", "GetVolume", "SetVolume", "SetVolume", "GetPositionInfo"])
        setvol = [ET.fromstring(x[2]) for x in FakeRenderer.bodies if x[3] == "SetVolume"]
        self.assertEqual([r.findtext(".//DesiredVolume") for r in setvol], ["100", "0"])
        first = ET.fromstring(FakeRenderer.bodies[0][2])
        metadata = first.findtext(".//CurrentURIMetaData")
        didl = ET.fromstring(metadata)
        self.assertEqual(didl.findtext(".//{http://purl.org/dc/elements/1.1/}title"), title)
        self.assertEqual(didl.findtext(".//{urn:schemas-upnp-org:metadata-1-0/upnp/}artist"), "Izvajalec & <x>")
        # item in res morata biti v imenskem prostoru DIDL-Lite (strogi renderji sicer zavrnejo metapodatke)
        self.assertIsNotNone(didl.find("{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}item/{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}res"))
        for _, soapaction, _, _ in FakeRenderer.bodies:
            self.assertTrue(soapaction.startswith('"urn:schemas-upnp-org:service:'))

    def test_soap_fault(self):
        FakeRenderer.fault = True
        with self.assertRaisesRegex(dlna.DlnaNapaka, "701.*Transition not available"):
            self.speaker().ustavi()

    def test_file_server(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "glasba.mp3"; path.write_bytes(b"0123456789")
            with dlna.StreznikDatotek(path, "127.0.0.1") as server:
                self.assertEqual(urllib.request.urlopen(server.url).read(), b"0123456789")
                req = urllib.request.Request(server.url, method="HEAD")
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Type"], "audio/mpeg")
                    self.assertEqual(response.headers["transferMode.dlna.org"], "Streaming")
                    self.assertIn("contentFeatures.dlna.org", response.headers)
                req = urllib.request.Request(server.url, headers={"Range": "bytes=2-5"})
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
                    self.assertEqual(response.read(), b"2345")
                wrong = urlsplit(server.url)._replace(path="/wrong/not-music.mp3").geturl()
                with self.assertRaises(Exception) as raised:
                    urllib.request.urlopen(wrong)
                self.assertEqual(getattr(raised.exception, "code", None), 404)


if __name__ == "__main__":
    unittest.main()
