import express from 'express';
import { get, put, BlobPreconditionFailedError, BlobNotFoundError } from '@vercel/blob';
import { pathToFileURL } from 'node:url';

export function createApp(storage = { get, put }) {
  const app = express();
  app.use(express.json({ limit: '2mb' }));
  app.use((req, res, next) => { res.set('Cache-Control', 'private, no-store'); next(); });
  const pathname = `neufert/${process.env.VERCEL_ENV || 'development'}/state.json`;
  app.get('/health', (req, res) => res.json({ ok: true }));
  app.get('/state', async (req, res) => {
    try {
      const blob = await storage.get(pathname, { access: 'private', useCache: false });
      if (!blob) return res.sendStatus(404);
      const text = await new Response(blob.stream).text();
      return res.set('ETag', blob.blob.etag).type('json').send(text);
    } catch (error) {
      if (error instanceof BlobNotFoundError) return res.sendStatus(404);
      return res.status(503).json({ detail: 'Durable state unavailable' });
    }
  });
  app.put('/state', async (req, res) => {
    if (!req.body || !Array.isArray(req.body.collections) || !Array.isArray(req.body.reviewed)) {
      return res.status(400).json({ detail: 'Invalid state schema' });
    }
    const etag = req.get('If-Match');
    // An absent ETag means create-only. Existing state is never blindly overwritten.
    const options = { access: 'private', addRandomSuffix: false, contentType: 'application/json',
      allowOverwrite: Boolean(etag), ...(etag ? { ifMatch: etag } : {}) };
    try {
      const result = await storage.put(pathname, JSON.stringify(req.body), options);
      return res.set('ETag', result.etag).json({ ok: true });
    } catch (error) {
      if (error instanceof BlobPreconditionFailedError || /already exists/i.test(error.message)) {
        return res.status(409).json({ detail: 'State changed; retry the operation' });
      }
      return res.status(503).json({ detail: 'Durable state could not be saved' });
    }
  });
  return app;
}
const app = createApp();
export default app;
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  app.listen(Number(process.env.PORT || 3002), '0.0.0.0');
}
