const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT || 5173);
const ROOT = __dirname;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ico': 'image/x-icon'
};

function resolveSafePath(urlPath) {
  const clean = urlPath.split('?')[0].split('#')[0];
  const requested = clean === '/' ? '/index.html' : clean;
  const normalized = path.normalize(requested).replace(/^(\.\.[/\\])+/, '');
  return path.join(ROOT, normalized);
}

const server = http.createServer((req, res) => {
  if (!req.url) {
    res.writeHead(400, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Bad Request');
    return;
  }

  const filePath = resolveSafePath(req.url);
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (error, data) => {
    if (error) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('Not Found');
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'content-type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  });
});

server.listen(PORT, HOST, () => {
  // eslint-disable-next-line no-console
  console.log(`frontend/web running at http://${HOST}:${PORT}`);
});
