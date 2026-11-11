// Prend les captures d'écran de la documentation (2880×1800) avec Chrome sans interface, piloté en CDP.
// Usage : node scripts/capture_screenshots.mjs <url du moteur> <dossier de sortie> <dossier de démonstration>
// Le moteur doit tourner avec TOKEN=tok. Le dossier de démonstration contient des fichiers FICTIFS (voir tests/make_fixtures.py).
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, outDir, demo] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9333;
const profile = mkdtempSync(join(tmpdir(), 'cdp-'));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--headless=new', '--hide-scrollbars',
  '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));

let ws, nextId = 1; const pending = new Map();
async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = list.find(t => t.type === 'page'); if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); break; }
    } catch (e) {}
    await sleep(200);
  }
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
}
const cdp = (method, params = {}) => new Promise(res => { const id = nextId++; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async js => { const r = await cdp('Runtime.evaluate', { expression: `(async () => { ${js} })()`, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) console.error(r.result.exceptionDetails.exception?.description); return r.result?.result?.value; };
async function shot(name) { await sleep(500); const r = await cdp('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(outDir, name), Buffer.from(r.result.data, 'base64')); console.log('✓', name); }

try {
  await connect();
  await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
  // On se fait passer pour l'app native : les boutons réservés à l'app (à côté de l'original, corbeille) apparaissent.
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: "window.NATIVE=true;window.TOKEN='tok';window.webkit={messageHandlers:{native:{postMessage(){}}}};" });
  await cdp('Page.navigate', { url }); await sleep(1500);
  await evaluate("localStorage.clear(); location.reload();"); await sleep(1500);

  const P = n => `${demo}/${n}`;
  const wait = `const wait = ms => new Promise(r => setTimeout(r, ms)); const idle = async () => { for (let i = 0; i < 120; i++) { if (!document.getElementById('launch').disabled && document.querySelectorAll('#list > li').length) return; await wait(250); } };`;
  const top = "window.scrollTo(0, 0);";

  // 1. Accueil
  await shot('01-accueil.png');

  // 2. File d'attente + bouton Lancer
  await evaluate(`${wait} await openPaths(['${P('Photo vacances.jpg')}','${P('Contrat.docx')}','${P('Lettre.pdf')}']); await wait(600); document.getElementById('queue').scrollIntoView({block:'start'}); window.scrollBy(0,-24); 1`);
  await shot('02-file-attente.png');

  // 3. Résultats d'un lot (réglages par défaut)
  await evaluate(`${wait} document.getElementById('launch').click(); await wait(800); await idle(); const li = document.querySelector('#list > li'); li.scrollIntoView({block:'start'}); window.scrollBy(0,-16); 1`);
  await shot('03-resultat-photo.png');
  await evaluate(`const li = document.querySelectorAll('#list > li')[1]; li.scrollIntoView({block:'start'}); window.scrollBy(0,-16); 1`);
  await shot('04-resultat-document.png');

  // 4. Masquage du contenu
  await evaluate(`${wait} ${top} document.querySelector('[data-opt=content]').click(); await wait(200); await openPaths(['${P('Contrat.docx')}','${P('Lettre.pdf')}']); await wait(600); document.getElementById('launch').click(); await wait(800); await idle(); document.querySelector('#list > li').scrollIntoView({block:'start'}); window.scrollBy(0,-16); 1`);
  await shot('05-contenu-masque.png');

  // 5. Mes propres métadonnées
  await evaluate(`${wait} document.querySelector('[data-opt=content]').click(); document.querySelector('[data-opt=setmeta]').click(); await wait(200);
    const set = (k, v) => { const i = document.querySelector('[data-mf=' + k + ']'); i.value = v; i.dispatchEvent(new Event('input')); };
    set('author', 'Anne Exemple'); set('title', 'Rapport trimestriel'); set('created', '2020-03-15T08:30'); set('make', 'MarqueTest'); set('model', 'X-T5'); set('lat', '43.2965'); set('lon', '5.3698');
    document.querySelector('[data-opt=setmeta]').scrollIntoView({block:'start'}); window.scrollBy(0,-24); 1`);
  await shot('06-mes-metadonnees.png');

  // 6. Un dossier entier
  await evaluate(`${wait} document.querySelector('[data-opt=setmeta]').click(); await wait(200); ${top} await openPaths(['${P('Dossier projet')}']); await wait(800); document.getElementById('launch').click(); await wait(1000); await idle(); document.querySelector('#list > li').scrollIntoView({block:'start'}); window.scrollBy(0,-16);
    const d = document.querySelector('#list details'); if (d) d.open = true; 1`);
  await shot('07-dossier.png');
} finally {
  chrome.kill();
}
