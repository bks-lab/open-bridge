// SPDX-License-Identifier: MIT
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const require = createRequire(new URL('../../ui/package.json', import.meta.url));
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const artifacts = process.env.UI_BROWSER_ARTIFACTS || fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-ui-shots-'));
fs.mkdirSync(artifacts, { recursive: true });
async function runs() {
  return page.evaluate(async () => (await (await fetch('/api/runs')).json()).runs);
}
async function until(check, message) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(message);
}
async function start(prompt, edit = false, client = 'Codex') {
  await page.getByRole('navigation').getByRole('button', { name: 'New task', exact: true }).click();
  await page.getByLabel('What should Bridge do?').fill(prompt);
  await page.getByRole('radio', { name: edit ? /^Edit/ : /^Inspect/ }).check();
  await page.getByRole('radio', { name: new RegExp(client, 'i') }).check();
  await page.getByRole('button', { name: 'Start task', exact: true }).click();
  await until(async () => (await runs()).some(run => run.prompt === prompt), 'Run not created');
}
try {
  await page.goto(process.argv[2]);
  await page.getByRole('button', { name: 'Neuer Auftrag', exact: true }).first().waitFor();
  const accessibility = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  assert.deepEqual(accessibility.violations.map(v => ({id:v.id, nodes:v.nodes.map(n=>n.target)})), [], 'Initial flight deck accessibility violations');
  const scene = page.locator('.planet-window');
  const frameBefore = await page.locator('.forward-viewport').boundingBox();
  const transformBefore = await scene.evaluate(el => getComputedStyle(el, '::before').transform);
  await page.evaluate(() => { const motion = document.getAnimations().find(a => a.animationName === 'orbital-drift'); if (!motion) throw new Error('Scene animation missing'); motion.currentTime = 50000; });
  assert.notEqual(await scene.evaluate(el => getComputedStyle(el, '::before').transform), transformBefore);
  assert.deepEqual(await page.locator('.forward-viewport').boundingBox(), frameBefore, 'Frame moved with planet');
  await page.getByRole('button', {name:'Ansicht pausieren', exact:true}).click();
  assert.equal(await scene.evaluate(el => getComputedStyle(el, '::before').animationPlayState), 'paused');
  await page.getByRole('button', {name:'Ansicht bewegen', exact:true}).click();
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await scene.evaluate(el => getComputedStyle(el, '::before').animationName), 'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  assert.equal(await page.getByText('Filmische Umgebung', {exact:true}).count(), 0);
  // The navigation gantry and viewport controls must fit intermediate widths too.
  for (const width of [390, 768, 800, 1024, 1440]) {
    await page.setViewportSize({width, height:1050});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Console overflow at ${width}`);
    const controls = await page.locator('.viewport-actions').boundingBox();
    const caption = await page.locator('.viewport-bottomline').boundingBox();
    assert.ok(controls.y + controls.height <= caption.y, `Viewport controls overlap caption at ${width}`);
  }
  await page.locator('button.theme').click();
  assert.deepEqual((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations.map(v => v.id), [], 'Light console accessibility violations');
  await page.locator('button.theme').click();
  await page.getByRole('button', { name: 'Language / Sprache' }).click();
  await page.getByText('Your projects', { exact: true }).waitFor();
  const bridgeSelector = page.getByLabel('Choose Bridge', { exact: true });
  const primaryId = await bridgeSelector.inputValue();
  const secondaryId = await bridgeSelector.locator('option').filter({ hasText: 'Secondary Bridge' }).getAttribute('value');
  assert.ok(secondaryId, 'Registered secondary Bridge missing');
  await bridgeSelector.selectOption(secondaryId);
  await page.getByRole('status').getByText('Files editable · CLI runs unavailable', { exact: true }).waitFor();
  await page.reload();
  await page.getByRole('status').getByText('Files editable · CLI runs unavailable', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('Choose Bridge', { exact: true }).inputValue(), secondaryId, 'Selection lost on reload');
  await page.getByRole('navigation').getByRole('button', { name: 'Bridge content', exact: true }).click();
  await page.getByLabel('Search file paths').fill('content-example.md');
  await page.locator('.file-row').filter({ hasText: 'docs/content-example.md' }).click();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Secondary-only document' }).waitFor();
  await page.getByRole('button', { name: 'Edit file', exact: true }).click();
  await page.getByLabel('File contents', { exact: true }).fill('# Edited secondary document\n');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByLabel('Choose Bridge', { exact: true }).selectOption(primaryId);
  assert.equal(await page.getByLabel('Choose Bridge', { exact: true }).inputValue(), secondaryId, 'Unsaved switch discarded draft');
  assert.equal(await page.getByLabel('File contents', { exact: true }).inputValue(), '# Edited secondary document\n');
  await page.getByRole('button', { name: 'Save file', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'File saved.' }).waitFor();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Edited secondary document' }).waitFor();
  await page.getByRole('button', { name: 'Edit file', exact: true }).click();
  await page.getByLabel('File contents', { exact: true }).fill('# Unsaved conflict draft\n');
  const concurrent = await page.evaluate(async (id) => {
    const headers = { 'X-Bridge-ID': id };
    const session = await (await fetch('/api/bootstrap', { headers })).json();
    const document = await (await fetch('/api/content?path=docs%2Fcontent-example.md', { headers })).json();
    const response = await fetch('/api/content', { method: 'POST', headers: { ...headers, 'X-Bridge-CSRF': session.csrf, 'Content-Type': 'application/json' }, body: JSON.stringify({ path: document.path, revision: document.revision, content: '# Concurrent secondary document\n' }) });
    return response.status;
  }, secondaryId);
  assert.equal(concurrent, 200);
  await page.getByRole('button', { name: 'Save file', exact: true }).click();
  await page.getByText(/Your draft is preserved/).waitFor();
  assert.equal(await page.getByLabel('File contents', { exact: true }).inputValue(), '# Unsaved conflict draft\n', 'Conflict lost draft');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Reload file', exact: true }).click();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Concurrent secondary document' }).waitFor();

  await page.getByRole('button', {name: 'Backups', exact: true}).click();
  await page.getByRole('button', {name: 'Load as draft', exact: true}).first().click();
  await page.getByText('Backup loaded as a draft. Review the changes and save to restore.').waitFor();
  assert.ok(await page.getByLabel('File contents', {exact: true}).inputValue());
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: 'Cancel editing', exact: true}).click();
  const otherTab = await context.newPage();
  await otherTab.goto(process.argv[2]);
  await otherTab.getByText('Your projects', { exact: true }).waitFor();
  assert.equal(await otherTab.getByLabel('Choose Bridge', { exact: true }).inputValue(), primaryId, 'Other tab changed active Bridge');
  await otherTab.close();
  assert.equal(await page.getByLabel('Choose Bridge', { exact: true }).inputValue(), secondaryId);
  await page.screenshot({ path: path.join(artifacts, 'bridge-selection.png'), fullPage: true });
  await page.getByLabel('Choose Bridge', { exact: true }).selectOption(primaryId);
  await page.getByText('Your projects', { exact: true }).waitFor();

  await page.screenshot({ path: path.join(artifacts, 'desktop.png'), fullPage: true });
  await page.getByRole('button', {name: '☆ Favorite', exact: true}).first().click();
  await page.getByLabel('Project view').selectOption('favorites');
  assert.equal(await page.locator('.project-tile').count(), 1);
  await page.getByRole('button', {name:'Archive in this browser',exact:true}).click();
  await page.getByRole('navigation').getByRole('button',{name:'New task',exact:true}).click();
  await page.getByLabel('What should Bridge do?').fill('Archived target must not run');
  assert.equal(await page.getByLabel('Project', {exact:true}).inputValue(), '');
  assert.equal(await page.getByRole('button',{name:'Start task',exact:true}).isDisabled(), true);
  await page.getByRole('navigation').getByRole('button',{name:'Overview',exact:true}).click();
  await page.getByLabel('Project view').selectOption('archived');
  await page.getByRole('button',{name:'Show in active projects',exact:true}).click();

  await page.getByLabel('Project view').selectOption('all');
  await page.getByRole('button', { name: 'Show all projects', exact: true }).click();
  assert.equal(await page.locator('.project-grid .project-card').count(), 20, 'Project tail inaccessible');
  await page.getByRole('navigation').getByRole('button', { name: 'Bridge content', exact: true }).click();
  await page.getByLabel('Search file paths').fill('Full Bridge content');
  await page.getByLabel('Search file contents', {exact: true}).check();
  await page.getByRole('button', {name: 'Search', exact: true}).click();
  await page.locator('.file-row').filter({hasText: 'docs/content-example.md'}).waitFor();
  assert.ok((await page.locator('.file-row').first().innerText()).includes('Line 1'));
  await page.getByLabel('Search file contents', {exact: true}).uncheck();
  await page.getByLabel('Search file paths').fill('content-example.md');
  await page.locator('.file-row').filter({ hasText: 'docs/content-example.md' }).click();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Full Bridge content' }).waitFor();
  assert.equal(await page.evaluate(() => window.contentExecuted), undefined, 'Document HTML executed');
  await page.screenshot({ path: path.join(artifacts, 'content-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: 'Edit file', exact: true }).click();
  await page.getByLabel('File contents', { exact: true }).fill('# English and German editor\n');
  await page.screenshot({ path: path.join(artifacts, 'editor-en.png'), fullPage: true });
  await page.getByRole('button', { name: 'Language / Sprache' }).click();
  await page.getByRole('button', { name: 'Datei speichern', exact: true }).waitFor();
  await page.screenshot({ path: path.join(artifacts, 'editor-de.png'), fullPage: true });
  assert.deepEqual((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations.map(v => v.id), [], 'Editor accessibility violations');
  await page.getByRole('button', { name: 'Language / Sprache' }).click();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Cancel editing', exact: true }).click();

  await page.getByLabel('Search file paths').fill('');
  await page.getByLabel('Category', { exact: true }).selectOption('docs');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.locator('.file-row').filter({ hasText: 'docs/page-64.md' }).click();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Indexed page 64' }).waitFor();
  await page.getByLabel('Category', { exact: true }).selectOption('identity');
  await page.locator('.file-row').filter({ hasText: 'SOUL.md' }).click();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Fixture principles.' }).waitFor();
  await page.getByLabel('Category', { exact: true }).selectOption('work');
  await page.getByLabel('Search file paths').fill('done/');
  await page.locator('.file-row').filter({ hasText: 'closed/STATUS.md' }).click();
  await page.locator('.content-document .markdown-preview').filter({ hasText: 'Historic work.' }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(artifacts, 'content-mobile.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Content mobile horizontal overflow');
  await page.setViewportSize({ width: 1440, height: 1050 });

  await start('inspect fixture');
  await page.reload();
  await page.getByRole('navigation').getByRole('button', { name: 'Runs', exact: true }).click();
  await until(async () => (await runs())[0]?.status === 'succeeded', 'Inspection did not complete');
  assert.equal((await runs()).length, 1, 'Reload duplicated run');
  await page.locator('.run-row').first().click();
  await page.getByText(/Browser client completed/).waitFor();
  await start('edit fixture', true);
  await until(async () => (await runs()).find(run => run.prompt === 'edit fixture')?.status === 'succeeded', 'Edit did not complete');
  await page.getByRole('tab', { name: 'Review changes' }).click();
  await page.getByText(/Browser-tested local edit/).waitFor();
  await start('slow task');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await until(async () => (await runs()).find(run => run.prompt === 'slow task')?.status === 'cancelled', 'Cancellation failed');
  await until(async () => await page.locator('.detail .badge').textContent() === 'Cancelled', 'Cancelled status not rendered');
  await start('vibe fixture', false, 'Vibe');
  await until(async () => (await runs()).find(run => run.prompt === 'vibe fixture')?.status === 'succeeded', 'Vibe did not complete');
  await page.getByRole('button', { name: 'Light theme', exact: true }).click();
  await page.getByRole('button', { name: 'Dark theme', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(artifacts, 'mobile.png'), fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile horizontal overflow');
  await page.route('**/api/runs', route => route.request().method() === 'POST' ? route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: 'Controlled browser conflict' }) }) : route.continue());
  await page.getByRole('navigation').getByRole('button', { name: 'New task', exact: true }).click();
  await page.getByLabel('What should Bridge do?').fill('request conflict');
  await page.getByRole('button', { name: 'Start task', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Controlled browser conflict' }).waitFor();
  assert.equal((await runs()).length, 4, 'Error created unexpected run');
  assert.deepEqual(errors, [], 'Browser runtime errors');
  console.log('Browser workflow passed: locale, inspect, reload, edit/diff, cancel, error, responsive layout. Screenshots: ' + artifacts);
} finally {
  // Failed assertions must not leave a long-running fixture worker behind.
  await page.evaluate(async () => {
    const bootstrap = await (await fetch('/api/bootstrap')).json();
    for (const run of bootstrap.runs) if (['queued', 'running'].includes(run.status))
      await fetch(`/api/runs/${run.id}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Bridge-CSRF': bootstrap.csrf }, body: '{}' });
  }).catch(() => {});
  await browser.close();
}
