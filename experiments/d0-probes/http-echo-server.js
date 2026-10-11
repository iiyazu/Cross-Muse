// D0 probe: minimal HTTP server. Logs every request (method, url, selected headers, body) to a file.
// usage: node http-echo-server.js <port> <host> <logfile>
const http = require('http');
const fs = require('fs');
const port = Number(process.argv[2] || 18080);
const host = process.argv[3] || '127.0.0.1';
const logfile = process.argv[4] || 'http-server.log';
http
  .createServer((req, res) => {
    let body = '';
    req.on('data', c => (body += c));
    req.on('end', () => {
      const rec = {
        t: new Date().toISOString(),
        method: req.method,
        url: req.url,
        remote: req.socket.remoteAddress,
        ua: req.headers['user-agent'],
        session: req.headers['x-xmuse-session'],
        body: body.slice(0, 300),
      };
      fs.appendFileSync(logfile, JSON.stringify(rec) + '\n');
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, pong: true, host, port, got: rec.session }));
    });
  })
  .listen(port, host, () => console.log(`listening ${host}:${port}`));
