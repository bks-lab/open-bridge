#!/usr/bin/env node
/**
 * Render a html-slides deck to PDF via Playwright headless Chromium.
 *
 * Why Playwright (not `chrome --print-to-pdf` directly):
 *  - Forces .visible on every .slide before render, because IntersectionObserver
 *    does not fire in headless print mode, so reveal children would otherwise
 *    stay at opacity 0.
 *  - Promotes loading="lazy" images to "eager" and waits until each one settled.
 *  - Waits for document.fonts.ready, then two animation frames for layout, so
 *    the embedded fonts are in before the page is printed. No fixed sleep.
 *
 * Page size:
 *  - no --width/--height: the deck's own CSS @page size wins (297x167 mm, 16:9,
 *    from slide-engine.css), with 297x167 mm as the fallback for a deck without one
 *  - --width/--height in mm: exactly that size; the CSS @page size is ignored
 *
 * Theme: --theme light|dark sets .theme-light / .theme-dark on <html> (the deck's
 * own switch) and the matching prefers-color-scheme, without touching storage.
 * Without the flag the deck renders as it would open: saved choice, else the OS
 * (headless Chromium reports light).
 *
 * Usage:
 *     node render-pdf.cjs <input.html> <output.pdf> [--width 297] [--height 167]
 *                         [--theme light|dark]
 *     node render-pdf.cjs --probe        # print where playwright was found
 *
 * Requires: playwright (npm i -g playwright; npx playwright install chromium).
 * It is looked up from the working directory, this script's folder, NODE_PATH,
 * the global npm root, Homebrew (/opt/homebrew, /usr/local) and every nvm node.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const USAGE = 'Usage: render-pdf.cjs <input.html> <output.pdf> [--width MM] [--height MM] [--theme light|dark]';
const DEFAULT_SIZE = { width: '297mm', height: '167mm' };

function searchPaths() {
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const dirs = [process.cwd(), __dirname];
  for (const p of (process.env.NODE_PATH || '').split(path.delimiter)) if (p) dirs.push(p);
  // the node running this script, and its global module folder
  const prefix = path.resolve(path.dirname(process.execPath), '..');
  dirs.push(path.join(prefix, 'lib', 'node_modules'), path.join(prefix, 'node_modules'));
  try {
    const root = require('child_process')
      .execFileSync('npm', ['root', '-g'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000 })
      .trim();
    if (root) dirs.push(root);
  } catch (e) { /* no npm on PATH */ }
  dirs.push('/opt/homebrew/lib/node_modules', '/usr/local/lib/node_modules');
  const nvmRoot = path.join(process.env.NVM_DIR || path.join(home, '.nvm'), 'versions', 'node');
  try {
    for (const v of fs.readdirSync(nvmRoot).sort().reverse()) dirs.push(path.join(nvmRoot, v, 'lib', 'node_modules'));
  } catch (e) { /* no nvm */ }
  return [...new Set(dirs)];
}

function resolvePlaywright() {
  const paths = searchPaths();
  for (const name of ['playwright', 'playwright-core']) {
    try {
      const where = require.resolve(name, { paths });
      return { where, mod: require(where) };
    } catch (e) { /* try the next name */ }
  }
  console.error('ERROR: playwright module not found. Install via: npm i -g playwright && npx playwright install chromium');
  console.error('Searched: ' + paths.join(', '));
  process.exit(1);
}

function mm(value) {
  const v = String(value).trim();
  if (!/^\d+(\.\d+)?(mm)?$/.test(v)) return null;
  return v.endsWith('mm') ? v : v + 'mm';
}

function usage(message) {
  if (message) console.error('ERROR: ' + message);
  console.error(USAGE);
  process.exit(2);
}

function parseArgs(argv) {
  const args = { input: null, output: null, width: null, height: null, theme: null, probe: false };
  const positional = [];
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--probe') args.probe = true;
    else if (a === '--width' || a === '--height') {
      const v = mm(argv[++i]);
      if (!v) usage(a + ' takes a size in mm');
      args[a.slice(2)] = v;
    } else if (a === '--theme') {
      const v = argv[++i];
      if (v !== 'light' && v !== 'dark') usage('--theme takes light or dark');
      args.theme = v;
    } else if (a === '-h' || a === '--help') { console.log(USAGE); process.exit(0); }
    else if (a.startsWith('--')) usage('unknown option ' + a);
    else positional.push(a);
  }
  args.input = positional[0];
  args.output = positional[1];
  return args;
}

function pdfOptions(args, outputPath) {
  const explicit = Boolean(args.width || args.height);
  return {
    path: outputPath,
    width: args.width || DEFAULT_SIZE.width,
    height: args.height || DEFAULT_SIZE.height,
    printBackground: true,
    // an explicit size must win over the deck's @page rule, a default must not
    preferCSSPageSize: !explicit,
    margin: { top: 0, bottom: 0, left: 0, right: 0 },
  };
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.probe) {
    console.log('playwright: ' + resolvePlaywright().where);
    return;
  }
  if (!args.input || !args.output) usage('input and output are required');
  const inputPath = path.resolve(args.input);
  const outputPath = path.resolve(args.output);
  if (!fs.existsSync(inputPath)) usage('input not found: ' + inputPath);

  const { chromium } = resolvePlaywright().mod;
  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      colorScheme: args.theme || 'light',
    });
    const page = await ctx.newPage();

    console.log('-> Loading file://' + inputPath);
    await page.goto('file://' + inputPath, { waitUntil: 'load' });
    await page.emulateMedia({ media: 'print', colorScheme: args.theme || 'light' });

    await page.evaluate(async (theme) => {
      const root = document.documentElement;
      if (theme) {
        root.classList.remove('theme-light', 'theme-dark');
        root.classList.add('theme-' + theme);
      }
      // 1. Every slide visible (IntersectionObserver does not fire in headless print)
      document.querySelectorAll('.slide').forEach((s) => s.classList.add('visible'));
      // 2. Lazy images load now, and every image has settled (loaded or failed)
      document.querySelectorAll('img[loading="lazy"]').forEach((img) => { img.loading = 'eager'; });
      await Promise.all(Array.from(document.images).map((img) => (img.complete
        ? Promise.resolve()
        : new Promise((res) => { img.onload = img.onerror = res; }))));
      // 3. Web fonts in, then two frames so layout reflects them
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
    }, args.theme);

    // 4. Live stages (slide-stage.js) add their frames when print starts; a PDF
    //    written before they load shows empty boxes. Wait for every frame's load
    //    event (bounded), then for the fonts inside each frame.
    const framed = await page.evaluate(async () => {
      // headless PDF output fires no beforeprint, and the print media change can
      // arrive after this runs: send it, so every listener (stage, reveals) acts now
      window.dispatchEvent(new Event('beforeprint'));
      await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
      const frames = Array.from(document.querySelectorAll('iframe'));
      await Promise.all(frames.map((f) => new Promise((res) => {
        let d = null;
        try { d = f.contentDocument; } catch (e) { return res(); } // another origin: nothing to wait on
        if (d && d.readyState === 'complete' && d.URL !== 'about:blank') return res();
        f.addEventListener('load', () => res(), { once: true });
        setTimeout(res, 8000);
      })));
      return frames.length;
    });
    for (const frame of page.frames()) {
      if (frame === page.mainFrame()) continue;
      await frame.evaluate(() => (document.fonts && document.fonts.ready ? document.fonts.ready.then(() => 0) : 0))
        .catch(() => 0);
    }
    if (framed) {
      await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))));
      console.log('-> Waited for ' + framed + ' embedded frame' + (framed === 1 ? '' : 's'));
    }

    const opts = pdfOptions(args, outputPath);
    if (!opts.preferCSSPageSize) {
      // Chromium still takes the orientation from a CSS @page size it was told to
      // ignore (a 210x297 request came out 297x210), so the explicit size is also
      // written as the last @page rule.
      await page.addStyleTag({ content: '@page { size: ' + opts.width + ' ' + opts.height + '; margin: 0; }' });
    }
    console.log('-> Rendering PDF (' + (opts.preferCSSPageSize ? 'CSS @page size, else ' : '')
      + opts.width + ' x ' + opts.height + (args.theme ? ', theme ' + args.theme : '') + ')');
    await page.pdf(opts);
    console.log('-> Wrote ' + outputPath);
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error(e && e.message ? e.message : e); process.exit(1); });
