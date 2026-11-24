import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../app/api/[[...path]]/route.ts', import.meta.url), 'utf8');
function handler(env, fetch) {
  const sandbox = { exports: {}, process: { env }, fetch, URL, Headers, Response };
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, sandbox);
  return sandbox.exports;
}

test('Vercel never falls back to localhost when its binding is absent', async () => {
  const api = handler({ VERCEL: '1', NEUFERT_API_URL: 'http://localhost:8000' }, () => assert.fail('unexpected fetch'));
  assert.equal((await api.GET(new Request('https://neufert.example/api/search'))).status, 503);
});

test('runtime binding preserves path, query, status and binary response', async () => {
  const api = handler({ NEUFERT_PIPELINE_URL: 'http://pipeline.internal:8080' }, async (url, options) => {
    assert.equal(url.href, 'http://pipeline.internal:8080/api/assets/page.webp?q=stairs');
    assert.equal(options.cache, 'no-store');
    return new Response(new Uint8Array([0, 255, 12]), { status: 206, headers: { 'content-type': 'image/webp' } });
  });
  const response = await api.GET(new Request('https://neufert.example/api/assets/page.webp?q=stairs'));
  assert.equal(response.status, 206);
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [0, 255, 12]);
});

test('same-origin collection writes retain body and reject cross-origin requests', async () => {
  let calls = 0;
  const api = handler({ NEUFERT_PIPELINE_URL: 'http://pipeline.internal' }, async (url, options) => {
    calls++;
    assert.equal(options.method, 'POST');
    assert.equal(options.headers.get('origin'), null);
    assert.equal(new TextDecoder().decode(options.body), '{"name":"Housing"}');
    return Response.json({ id: 'collection' });
  });
  const request = origin => new Request('https://neufert.example/api/collections', {
    method: 'POST', headers: { origin, 'content-type': 'application/json' }, body: '{"name":"Housing"}',
  });
  assert.equal((await api.POST(request('https://neufert.example'))).status, 200);
  assert.equal((await api.POST(request('https://other.example'))).status, 403);
  assert.equal(calls, 1);
});

test('local servers remain usable and backend failures return 502', async () => {
  const api = handler({}, async url => {
    assert.equal(url.href, 'http://127.0.0.1:8000/api/status');
    throw new Error('offline');
  });
  assert.equal((await api.GET(new Request('http://localhost:3000/api/status'))).status, 502);
});
