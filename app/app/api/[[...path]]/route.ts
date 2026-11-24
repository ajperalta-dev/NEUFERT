export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const hopHeaders = [
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length',
];

async function proxy(request: Request) {
  // Read bindings inside the function, never in build configuration or middleware.
  const base = process.env.NEUFERT_PIPELINE_URL ||
    (!process.env.VERCEL ? process.env.NEUFERT_API_URL || 'http://127.0.0.1:8000' : undefined);
  if (!base) {
    return Response.json({ detail: 'Pipeline service binding is unavailable.' }, { status: 503 });
  }
  const incoming = new URL(request.url);
  const origin = request.headers.get('origin');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method) && origin && origin !== incoming.origin) {
    return Response.json({ detail: 'Cross-origin writes are not allowed.' }, { status: 403 });
  }
  try {
    const target = new URL(base);
    // Assign the path rather than resolving user input as a URL: the host stays bound.
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    const headers = new Headers(request.headers);
    for (const key of [...hopHeaders, 'origin', 'forwarded', 'x-forwarded-host', 'x-forwarded-proto']) {
      headers.delete(key);
    }
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: 'no-store',
      redirect: 'manual',
      signal: request.signal,
    });
    const responseHeaders = new Headers(upstream.headers);
    for (const key of hopHeaders) responseHeaders.delete(key);
    // fetch decompresses the body before it is streamed to the browser.
    responseHeaders.delete('content-encoding');
    responseHeaders.set('cache-control', 'private, no-store');
    const location = responseHeaders.get('location');
    if (location) {
      const redirect = new URL(location, target);
      if (redirect.origin === target.origin) {
        redirect.protocol = incoming.protocol;
        redirect.host = incoming.host;
        responseHeaders.set('location', redirect.toString());
      }
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: 'Pipeline service could not be reached.' }, { status: 502 });
  }
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
