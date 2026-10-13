'use strict';
// Safeer DRM: predvajalnik zaščitenih vsebin (Widevine prek castLabs ECS) za Splet in Safeer predvajalnik.
//
// Vdelani način (tako ga zažene Safeer OS; isti dogovor kot SafeerMediaWebView.exe):
//   safeer-drm --parent=<okno> --url=<https> --profile=<mapa> --state=<events.jsonl> --command=<command.txt>
//   Okno je brez okvirja in brez gumba v opravilni vrstici; v »events.jsonl« zapiše WINDOW_HANDLE, Safeer OS
//   ga vstavi v svoje okno (uporabnik vidi isti predvajalnik kot vedno). Ukazi v command.txt: back, reload.
// Samostojni način (za preizkus): safeer-drm <https-URL>
const fs = require('fs');
const path = require('path');
const { app, components, BrowserWindow, session, webFrameMain } = require('electron');

const argumenti = {};
for (const a of process.argv.slice(1)) {
  const m = /^--([a-z]+)=(.*)$/i.exec(a);
  if (m) argumenti[m[1].toLowerCase()] = m[2];
}
const vdelan = Boolean(argumenti.parent);
// Storitev (Netflix, Disney+ ...): uporabnik sam brska in se prijavlja - brez samodejnega klika in brez omejitve domene.
const storitev = argumenti.storitev === '1';
const PREIZKUS = 'https://bitmovin.com/demos/drm';
const statePath = argumenti.state || '';
const commandPath = argumenti.command || '';

function zapisi(type, detail = '') {
  if (!statePath) { console.log(`[safeer-drm] ${type} ${detail}`); return; }
  try { fs.appendFileSync(statePath, JSON.stringify({ time: new Date().toISOString(), type, detail }) + '\n'); } catch (_) {}
}
function varenGostitelj(raw) { try { return new URL(raw).hostname; } catch (_) { return 'invalid'; } }
function osnovnaDomena(host) { const d = host.replace(/^\.+|\.+$/g, '').toLowerCase().split('.'); return d.length >= 2 ? d.slice(-2).join('.') : host.toLowerCase(); }

function zacetniUrl() {
  const kandidati = vdelan ? [argumenti.url] : process.argv.slice(1);
  for (const a of kandidati) { try { const u = new URL(a); if (u.protocol === 'https:') return u.href; } catch (_) {} }
  return vdelan ? null : PREIZKUS;
}
const prviUrl = zacetniUrl();
if (vdelan && !prviUrl) { process.exitCode = 2; app.quit(); }

// Profil (piškotki, predpomnilnik) je za vsako sejo svoj, kot pri WebView2; Widevine modul ostane v
// skupni mapi aplikacije, da se ne prenaša ob vsakem predvajanju.
if (argumenti.profile) { fs.mkdirSync(argumenti.profile, { recursive: true }); app.setPath('sessionData', argumenti.profile); }
// Samo za meritve: SAFEER_DRM_CDP=<vrata> odpre razhroščevanje na 127.0.0.1 (Safeer OS te spremenljivke nikoli ne nastavi).
if (/^\d{4,5}$/.test(process.env.SAFEER_DRM_CDP || '')) { app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1'); app.commandLine.appendSwitch('remote-debugging-port', process.env.SAFEER_DRM_CDP); }
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
app.commandLine.appendSwitch('disable-background-mode');
app.commandLine.appendSwitch('host-resolver-rules', 'MAP *.cfd 127.0.0.1, MAP *.buzz 127.0.0.1, MAP *.monster 127.0.0.1, MAP *.top 127.0.0.1, MAP *.click 127.0.0.1');
// Strani naj vidijo navaden Chrome (nekateri ponudniki zavrnejo »Electron« v UA).
app.userAgentFallback = app.userAgentFallback.replace(/ (Electron|safeer-drm|SafeerDRM|Safeer DRM)\/\S+/g, '');

const ZAPRTE_KONCNICE = ['monetag.com', '20bet.com', '1xbet.com', 'onclick.com', 'popunder.net', 'popcash.net', 'popads.net',
  'propellerads.com', 'exoclick.com', 'adsterra.com', 'juicyads.com', 'trafficjunky.com', 'adnxs.com', 'criteo.com', 'histats.com',
  'doubleclick.net', 'googlesyndication.com', 'clarity.ms', 'hotjar.com', 'bet365.com', 'parimatch.com', 'vulkan.com',
  'mostbet.com', 'pinup.com', 'admaven.com', 'hilltopads.com', 'a-ads.com'];
const ZAPRTI_ZNAKI = ['monetag', '20bet', '1xbet', 'onclick', 'popunder', 'popcash', 'popads', 'propellerads', 'exoclick',
  'adsterra', 'juicyads', 'trafficjunky', 'adnxs', 'criteo', 'histats', 'doubleclick', 'googlesyndication', 'disable-devtool',
  'clarity.ms', 'hotjar', 'bet365', 'parimatch', 'vulkan', 'mostbet', 'pinup', 'admaven', 'hilltopads', 'a-ads', '23vlcfp', '2lizguk'];
function zaprtGostitelj(raw) {
  let u; try { u = new URL(raw); } catch (_) { return ''; }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return '';
  const h = u.hostname.replace(/\.$/, '').toLowerCase();
  if (h === '127.0.0.1' || h === 'localhost' || h === 'tmdb.org' || h.endsWith('.tmdb.org') || h === 'themoviedb.org' || h.endsWith('.themoviedb.org')) return '';
  if (ZAPRTE_KONCNICE.some(d => h === d || h.endsWith('.' + d))) return h;
  const deli = h.split('.');
  return ZAPRTI_ZNAKI.some(z => deli.some(d => d.includes(z))) ? h : '';
}

const PREVERI_PREDVAJANJE = "(() => Array.from(document.querySelectorAll('video,audio')).some(m => !m.paused && !m.ended && m.readyState >= 2 && m.currentTime > 0))()";
const SAMODEJNI_ZAGON = `(() => {
  if (window.__safeerAutoplayInstalled) return true;
  window.__safeerAutoplayInstalled = true;
  const play = () => {
    document.querySelectorAll('video,audio').forEach(m => { try { m.muted = false; m.volume = 1.0; const p = m.play(); if (p) p.catch(() => {}); } catch (_) {} });
    const b = document.querySelector('[aria-label="Play"], [title="Play"], .vjs-big-play-button, .jw-icon-display, .plyr__control--overlaid, [data-plyr="play"], .play-button');
    if (b) { try { b.click(); } catch (_) {} }
  };
  const subtitlesOff = () => document.querySelectorAll('video').forEach(v => { try { Array.from(v.textTracks || []).forEach(t => { t.mode = 'disabled'; }); } catch (_) {} });
  const poke = () => {
    play();
    const media = Array.from(document.querySelectorAll('video,audio'));
    if (!media.some(m => !m.paused && m.readyState >= 2)) {
      const e = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
      if (e) { try { e.click(); } catch (_) {} }
      setTimeout(play, 300);
    }
  };
  subtitlesOff(); setTimeout(subtitlesOff, 800); setTimeout(subtitlesOff, 2200);
  play(); setTimeout(play, 1200); setTimeout(play, 3000);
  setTimeout(poke, 4500); setTimeout(poke, 7000); setTimeout(poke, 9500);
  return true;
})();`;

let okno = null;
let predvajanjeZacelo = false;
let medijZaznan = false;
let napakHttp = 0;
let klikov = 0;
let okvirjevJavljenih = 0;
let casovnikKlika = null;

function zacniKlik() {
  if (!vdelan || storitev || klikov > 0 || casovnikKlika) return;
  // En pravi klik na sredino, če stran zavrne samodejni zagon (kot WebView2 predvajalnik).
  casovnikKlika = setTimeout(() => {
    if (predvajanjeZacelo || !okno) return;
    klikov++;
    const [w, h] = okno.getContentSize();
    const x = Math.max(1, Math.floor(w / 2)), y = Math.max(1, Math.floor(h / 2));
    try {
      okno.webContents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
      okno.webContents.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: 1 });
      zapisi('PLAY_CLICK', String(klikov));
    } catch (e) { zapisi('PLAY_CLICK_FAILED', e.name || 'Error'); }
  }, 2500);
}

function vsiOkvirji() { try { return okno.webContents.mainFrame.framesInSubtree; } catch (_) { return []; } }

async function preveriPredvajanje() {
  if (predvajanjeZacelo || !okno) return;
  for (const f of vsiOkvirji()) {
    try { if (await f.executeJavaScript(PREVERI_PREDVAJANJE) === true) { predvajanjeZacelo = true; zapisi('PLAYBACK_STARTED', varenGostitelj(prviUrl)); return; } } catch (_) {}
  }
}

function obdelajUkaz() {
  if (!commandPath || !okno || !fs.existsSync(commandPath)) return;
  try {
    const ukaz = fs.readFileSync(commandPath, 'utf8').trim().toLowerCase();
    fs.unlinkSync(commandPath);
    const zg = okno.webContents.navigationHistory;
    if (ukaz === 'back' && zg.canGoBack()) zg.goBack();
    else if (ukaz === 'reload') okno.webContents.reload();
    else if (ukaz === 'exitfullscreen') okno.webContents.executeJavaScript('document.fullscreenElement && document.exitFullscreen()').catch(() => {});
  } catch (_) {}
}

function nastaviSejo(ses) {
  const dovoljeno = new Set(['mediaKeySystem', 'protectedMediaIdentifier', 'fullscreen']);
  ses.setPermissionRequestHandler((_wc, p, cb) => { const ok = dovoljeno.has(p); if (!ok) zapisi('PERMISSION_BLOCKED', p); cb(ok); });
  ses.setPermissionCheckHandler((_wc, p) => dovoljeno.has(p));
  ses.on('will-download', (e) => { e.preventDefault(); zapisi('DOWNLOAD_BLOCKED'); });
  ses.webRequest.onBeforeRequest((d, cb) => {
    const h = zaprtGostitelj(d.url);
    if (h) { zapisi('AD_OR_THREAT_RESOURCE_BLOCKED', h); cb({ cancel: true }); } else cb({});
  });
  ses.webRequest.onCompleted((d) => {
    const status = d.statusCode || 0;
    const glave = d.responseHeaders || {};
    const kljuc = Object.keys(glave).find(k => k.toLowerCase() === 'content-type');
    const tip = kljuc ? String(glave[kljuc][0] || '').toLowerCase() : '';
    if (status >= 400 && napakHttp < 30) { napakHttp++; zapisi('HTTP_ERROR', `${varenGostitelj(d.url)} status=${status} type=${tip}`); }
    if (medijZaznan || status < 200 || status >= 300) return;
    let pot = ''; try { pot = new URL(d.url).pathname.toLowerCase(); } catch (_) {}
    const medijPot = ['.m3u8', '.mpd', '.m4s', '.ts', '.mp4', '.webm'].some(k => pot.endsWith(k));
    const medijTip = tip.startsWith('video/') || tip.startsWith('audio/') || tip.includes('mpegurl') || tip.includes('dash+xml');
    if (d.resourceType === 'media' || medijPot || medijTip) { medijZaznan = true; zapisi('MEDIA_RESPONSE', varenGostitelj(d.url)); }
  });
}

function odpri(url) {
  okno = new BrowserWindow({
    width: 1280, height: 720, backgroundColor: '#000000', autoHideMenuBar: true, title: 'Safeer',
    // Vdelan: brez okvirja, brez gumba v opravilni vrstici, zunaj zaslona, dokler ga Safeer OS ne vstavi v svoje okno.
    frame: !vdelan, skipTaskbar: vdelan, x: vdelan ? -32000 : undefined, y: vdelan ? -32000 : undefined,
    show: !vdelan, focusable: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true, backgroundThrottling: false }
  });
  okno.setMenu(null);
  if (vdelan) {
    const rocaj = okno.getNativeWindowHandle();
    const stevilka = rocaj.length >= 8 ? rocaj.readBigUInt64LE(0) : BigInt(rocaj.readUInt32LE(0));
    zapisi('WINDOW_HANDLE', stevilka.toString());
    okno.showInactive();
  }
  const wc = okno.webContents;
  wc.setWindowOpenHandler(({ url: cilj }) => {
    // Storitev: novo okno (npr. prijava) odpremo v istem predvajalniku; drugje pojavna okna zapremo.
    if (storitev && cilj.startsWith('https:')) { wc.loadURL(cilj); zapisi('POPUP_IN_PLACE', varenGostitelj(cilj)); }
    else zapisi('POPUP_BLOCKED');
    return { action: 'deny' };
  });
  const zacetnaDomena = osnovnaDomena(varenGostitelj(url));
  wc.on('will-navigate', (e, cilj) => {
    let u = null; try { u = new URL(cilj); } catch (_) {}
    zapisi('NAVIGATION_START', `${varenGostitelj(cilj)} redirected=False`);
    if (vdelan && !storitev && (!u || u.protocol !== 'https:' || osnovnaDomena(u.hostname) !== zacetnaDomena)) { e.preventDefault(); zapisi('NAVIGATION_BLOCKED', varenGostitelj(cilj)); }
    else if (!u || u.protocol !== 'https:') e.preventDefault();
  });
  wc.on('certificate-error', (e, cilj, _err, _cert, cb) => { e.preventDefault(); cb(false); zapisi('CERTIFICATE_BLOCKED', varenGostitelj(cilj)); });
  wc.on('render-process-gone', (_e, d) => zapisi('PROCESS_FAILED', d.reason));
  wc.on('did-frame-finish-load', (_e, glavni, procId, routingId) => {
    if (!storitev) { try { const f = webFrameMain.fromId(procId, routingId); if (f) f.executeJavaScript(SAMODEJNI_ZAGON).catch(() => {}); } catch (_) {} }
    if (!glavni && okvirjevJavljenih < 5) { okvirjevJavljenih++; zapisi('FRAME_READY'); }
    zacniKlik();
  });
  wc.on('did-finish-load', () => zapisi('NAVIGATION_OK', 'Success'));
  wc.on('did-fail-load', (_e, koda, opis, _u, glavni) => { if (glavni && koda !== -3) zapisi('NAVIGATION_FAILED', opis); });
  let htmlCelozaslonsko = false;
  wc.on('enter-html-full-screen', () => { htmlCelozaslonsko = true; zapisi('FULLSCREEN_ON'); });
  wc.on('leave-html-full-screen', () => { htmlCelozaslonsko = false; zapisi('FULLSCREEN_OFF'); });
  wc.on('before-input-event', (e, i) => {
    if (i.type !== 'keyDown') return;
    if (!vdelan && i.key === 'F11') { okno.setFullScreen(!okno.isFullScreen()); e.preventDefault(); }
    // Esc zapre celozaslonski video (kot v Chromu); Electron tega sam ne naredi.
    else if (i.key === 'Escape' && htmlCelozaslonsko) { wc.executeJavaScript('document.exitFullscreen && document.exitFullscreen()').catch(() => {}); e.preventDefault(); }
    else if (!vdelan && i.key === 'Escape' && okno.isFullScreen()) okno.setFullScreen(false);
  });
  okno.on('closed', () => { okno = null; app.quit(); });
  okno.loadURL(url);
  zapisi('SESSION_READY', varenGostitelj(url));
  if (vdelan) { setInterval(obdelajUkaz, 200); setInterval(preveriPredvajanje, 750); }
}

if (prviUrl) {
  app.whenReady().then(async () => {
    nastaviSejo(session.defaultSession);
    try {
      // Prvi zagon prenese Widevine (nekaj sekund); brez omrezja do Googla ne cakamo v nedogled.
      await Promise.race([components.whenReady(), new Promise((_, ne) => setTimeout(() => ne(new Error('Widevine ni pripravljen v 15 s')), 15000))]);
      const s = components.status();
      const wv = Object.values(s).find(c => /widevine/i.test(c.title || '')) || {};
      zapisi('DRM_READY', `widevine ${wv.version || '?'} ${wv.status || ''}`.trim());
    } catch (e) {
      // Brez Widevine se odprta stran vseeno naloži (video brez DRM dela naprej).
      zapisi('DRM_FAILED', String(e && e.message || e).slice(0, 200));
    }
    odpri(prviUrl);
  }).catch(e => { zapisi('START_FAILED', String(e && e.message || e).slice(0, 200)); app.exit(3); });
  app.on('window-all-closed', () => app.quit());
}
