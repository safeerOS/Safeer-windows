#!/usr/bin/env node
// Template add-on for Safeer (and every Stremio client) - Node.js 18+, no dependencies.
//
//   node addon.mjs 7000        ->  http://<this computer's IP>:7000/manifest.json
//
// A Stremio add-on (manifest, catalog, meta, stream) plus the optional Safeer extensions (an action, enrich, a
// folder and settings that arrive in the X-Safeer-Config header) and polite rate limiting (429 + Retry-After).
// Replace CATALOG and the stream lookup with your own content; serve it over https in production.
// Predloga dodatka: zamenjaj CATALOG in iskanje tokov s svojo vsebino. Licence: Apache-2.0.
import http from 'node:http';
import { pathToFileURL } from 'node:url';

export const MANIFEST = {
  id: 'org.example.template',            // your own reverse-domain id, never change it after publishing
  version: '1.0.0',                      // semver; bump it with every change users should see
  name: 'Template add-on',
  description: 'Example add-on for the Safeer Add-on Protocol v1',
  resources: ['catalog', 'meta', 'stream'],
  types: ['movie'],
  idPrefixes: ['example:'],
  catalogs: [{ type: 'movie', id: 'example', name: 'Examples' }],
  // Optional Safeer extensions - other Stremio clients ignore this key.
  safeer: {
    protocol: 1,
    actions: [{ id: 'add-to-list', on: ['movie'], icon: 'plus',
      label: { en: 'Add to my list', sl: 'Dodaj na moj seznam' } }],
    enrich: ['movie'],
    folders: [{ id: 'my-list', name: { en: 'My list', sl: 'Moj seznam' } }],
    settings: [
      { key: 'api_key', type: 'secret', label: { en: 'API key', sl: 'Ključ API' } },
      { key: 'quality', type: 'choice', options: ['auto', '1080p', '720p'], default: 'auto',
        label: { en: 'Quality', sl: 'Kakovost' } },
    ],
    changelog: { '1.0.0': { en: 'First version', sl: 'Prva različica' } },
  },
};

// Your content. Big Buck Bunny (c) Blender Foundation, CC BY 3.0 - a freely licensed sample.
const CATALOG = [
  { id: 'example:bbb', type: 'movie', name: 'Big Buck Bunny', releaseInfo: '2008',
    poster: 'https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg',
    stream: 'https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4' },
];
const myList = [];                       // filled by the action; in memory only - use your own storage

const RATE = 120, WINDOW_MS = 60_000;    // per client address, then 429 with Retry-After
const hits = new Map();

/** Settings Safeer sends: X-Safeer-Config = base64url(JSON). Secrets arrive only over https. */
function config(req) {
  const raw = req.headers['x-safeer-config'];
  if (!raw) return {};
  try {
    const v = JSON.parse(Buffer.from(String(raw), 'base64url').toString('utf8'));
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch { return {}; }
}

const find = (id) => CATALOG.find((m) => m.id === id);
const card = ({ id, type, name, poster, releaseInfo }) => ({ id, type, name, poster, releaseInfo });

function send(res, status, body, headers = {}) {
  const data = Buffer.from(JSON.stringify(body), 'utf8');
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'max-age=300', 'Content-Length': data.length, ...headers });
  res.end(data);
}

function limited(req, res) {
  const now = Date.now(), who = req.socket.remoteAddress || '';
  if (hits.size > 10000)                  // forget old addresses - a public server sees many
    for (const [k, v] of hits) if (now - v.start > WINDOW_MS) hits.delete(k);
  let h = hits.get(who);
  if (!h || now - h.start > WINDOW_MS) h = { start: now, count: 0 };
  h.count++;
  hits.set(who, h);
  if (h.count <= RATE) return false;
  send(res, 429, { error: 'rate limit' }, { 'Retry-After': String(Math.ceil((WINDOW_MS - (now - h.start)) / 1000)) });
  return true;
}

function route(req, res) {
  const path = new URL(req.url, 'http://x').pathname;
  if (path === '/manifest.json') return send(res, 200, MANIFEST);
  let tail = path.replace(/^\/+|\/+$/g, '');
  if (tail.endsWith('.json')) tail = tail.slice(0, -5);
  const p = tail.split('/').map(decodeURIComponent);    // decode each part: ids may contain "/" or ":"

  if (p.length >= 3 && p[0] === 'catalog' && p[1] === 'movie' && p[2] === 'example')
    return send(res, 200, { metas: CATALOG.map(card) });
  if (p.length === 3 && p[0] === 'meta') {
    const m = find(p[2]);
    return m ? send(res, 200, { meta: card(m) }) : send(res, 404, { error: 'not found' });
  }
  if (p.length === 3 && p[0] === 'stream') {
    const m = find(p[2]);
    const quality = config(req).quality || 'auto';       // a setting chosen by the user in Safeer
    return send(res, 200, { streams: m ? [{ name: 'Template', title: `360p sample (${quality})`, url: m.stream }] : [] });
  }
  // ---- Safeer extensions (docs/DODATKI-PROTOKOL.md section 3)
  if (p.length === 5 && p[0] === 'safeer' && p[1] === 'action' && p[2] === 'add-to-list') {
    if (!myList.includes(p[4])) myList.push(p[4]);
    const hasKey = 'api_key' in config(req);            // use the secret; never send it back or log it
    return send(res, 200, { ok: true, refresh: false, message: {
      en: 'Added' + (hasKey ? ' (with API key)' : ''), sl: 'Dodano' + (hasKey ? ' (s ključem API)' : '') } });
  }
  if (p.length === 4 && p[0] === 'safeer' && p[1] === 'enrich')
    return send(res, 200, { meta: { description: 'A giant rabbit and three bullies.', imdbRating: '7.2', language: 'en' } });
  if (p.join('/') === 'safeer/folder/my-list')
    return send(res, 200, { items: [{ kind: 'folder', path: 'all', name: 'All' }] });
  if (p.join('/') === 'safeer/folder/my-list/all')
    return send(res, 200, { items: myList.map(find).filter(Boolean).map((m) => ({ kind: 'meta', ...card(m) })) });
  return send(res, 404, { error: 'not found' });
}

export function createServer() {
  return http.createServer((req, res) => {
    if (req.method !== 'GET') return send(res, 405, { error: 'GET only' });
    if (limited(req, res)) return;
    try { route(req, res); } catch { send(res, 500, { error: 'server' }); }   // never leak a stack trace
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.argv[2] || 7000);
  createServer().listen(port, '0.0.0.0', () =>
    console.log(`Add-on: http://<this computer's IP>:${port}/manifest.json  (Ctrl+C to stop)`));
}
