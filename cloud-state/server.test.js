import { test } from 'node:test';
import assert from 'node:assert/strict';
import { BlobPreconditionFailedError } from '@vercel/blob';
import { createApp } from './server.js';

test('state survives instances and stale ETags cannot overwrite changes', async () => {
  let saved = null, version = 0;
  const storage = {
    async get() {
      return saved ? { stream: new Response(JSON.stringify(saved)).body, blob: { etag: String(version) } } : null;
    },
    async put(path, text, options) {
      if (saved && (!options.allowOverwrite || options.ifMatch !== String(version))) throw new BlobPreconditionFailedError();
      saved = JSON.parse(text); version++; return { etag: String(version) };
    },
  };
  async function run(instance) {
    const server = createApp(storage).listen(0, '127.0.0.1');
    await new Promise(resolve => server.on('listening', resolve));
    try { await instance(`http://127.0.0.1:${server.address().port}/state`); }
    finally { await new Promise(resolve => server.close(resolve)); }
  }
  const state = { collections: [{ id: 'favorites', name: 'Favoritos', entries: [] }], reviewed: [] };
  await run(async url => {
    assert.equal((await fetch(url)).status, 404);
    const first = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state) });
    assert.equal(first.status, 200);
    const stale = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'If-Match': 'stale' }, body: JSON.stringify(state) });
    assert.equal(stale.status, 409);
  });
  await run(async url => {
    const restored = await fetch(url);
    assert.deepEqual(await restored.json(), state);
    assert.equal(restored.headers.get('etag'), '1');
    const noPrecondition = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state) });
    assert.equal(noPrecondition.status, 409);
    const updated = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'If-Match': '1' }, body: JSON.stringify({ ...state, reviewed: ['entry'] }) });
    assert.equal(updated.status, 200);
  });
});
