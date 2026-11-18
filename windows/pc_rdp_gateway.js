'use strict';

/**
 * Windows PC Background RDP Gateway (0.0.0.0:5051)
 * - Không phụ thuộc thư viện ngoài (100% Node.js gốc: http, crypto, net, tls)
 * - Triển khai chuẩn giao thức RDCleanPath (ASN.1 DER) của IronRDP sang 127.0.0.1:3389
 * - Hỗ trợ độ phân giải 2248x1080 @ 100% scaling, NLA CredSSP, Clipboard, Touch & Chuột KVM
 */

const http = require('http');
const crypto = require('crypto');
const net = require('net');
const tls = require('tls');
const os = require('os');

const LISTEN_HOST = '0.0.0.0';
const LISTEN_PORT = Number(process.env.PC_GATEWAY_PORT || 5051);
const WS_MAGIC_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

// ── RDCleanPath ASN.1 DER Constants ──
const VERSION_1 = 3390; // 3389 + 1
const TAG_SEQUENCE = 0x30;
const TAG_INTEGER = 0x02;
const TAG_OCTET_STRING = 0x04;
const TAG_UTF8STRING = 0x0c;
const TAG_CTX = (n) => 0xa0 + n;

function derEncodeLength(length) {
  if (length < 0x80) return Buffer.from([length]);
  const bytes = [];
  let temp = length;
  while (temp > 0) {
    bytes.unshift(temp & 0xff);
    temp >>= 8;
  }
  return Buffer.from([0x80 | bytes.length, ...bytes]);
}

function derWrap(tag, content) {
  return Buffer.concat([Buffer.from([tag]), derEncodeLength(content.length), content]);
}

function derEncodeInteger(value) {
  if (value === 0) return derWrap(TAG_INTEGER, Buffer.from([0]));
  const bytes = [];
  let temp = value;
  while (temp > 0) {
    bytes.unshift(temp & 0xff);
    temp >>= 8;
  }
  if (bytes[0] & 0x80) bytes.unshift(0);
  return derWrap(TAG_INTEGER, Buffer.from(bytes));
}

function derEncodeUtf8String(str) {
  return derWrap(TAG_UTF8STRING, Buffer.from(str, 'utf-8'));
}

function derEncodeOctetString(buf) {
  return derWrap(TAG_OCTET_STRING, buf);
}

function derWrapContext(tagNum, content) {
  return derWrap(TAG_CTX(tagNum), content);
}

function derDecodeLength(buf, offset) {
  const first = buf[offset];
  if (first < 0x80) return { length: first, bytesRead: 1 };
  const numBytes = first & 0x7f;
  let length = 0;
  for (let i = 0; i < numBytes; i++) {
    length = (length * 256) + buf[offset + 1 + i];
  }
  return { length, bytesRead: 1 + numBytes };
}

function derDecodeTLV(buf, offset) {
  const tag = buf[offset];
  const { length, bytesRead } = derDecodeLength(buf, offset + 1);
  const headerLen = 1 + bytesRead;
  const value = buf.subarray(offset + headerLen, offset + headerLen + length);
  return { tag, value, totalLength: headerLen + length };
}

function derDecodeInteger(buf) {
  let val = 0;
  for (let i = 0; i < buf.length; i++) {
    val = (val * 256) + buf[i];
  }
  return val;
}

function derDecodeChildren(buf) {
  const children = [];
  let offset = 0;
  while (offset < buf.length) {
    const tlv = derDecodeTLV(buf, offset);
    children.push(tlv);
    offset += tlv.totalLength;
  }
  return children;
}

function parseRDCleanPathRequest(data) {
  const buf = Buffer.isBuffer(data) ? data : Buffer.from(data);
  const outer = derDecodeTLV(buf, 0);
  if (outer.tag !== TAG_SEQUENCE) {
    throw new Error(`Expected SEQUENCE (0x30), got 0x${outer.tag.toString(16)}`);
  }
  const children = derDecodeChildren(outer.value);
  let version = null;
  let destination = null;
  let x224ConnectionRequest = null;

  for (const child of children) {
    const ctxTag = child.tag & 0x1f;
    if (ctxTag === 0) {
      version = derDecodeInteger(derDecodeTLV(child.value, 0).value);
    } else if (ctxTag === 2) {
      destination = derDecodeTLV(child.value, 0).value.toString('utf-8');
    } else if (ctxTag === 6) {
      x224ConnectionRequest = Buffer.from(derDecodeTLV(child.value, 0).value);
    }
  }

  if (version !== VERSION_1) {
    throw new Error(`Unsupported RDCleanPath version: ${version}`);
  }
  if (!destination || !x224ConnectionRequest) {
    throw new Error('Missing destination or x224_connection_pdu');
  }
  return { destination, x224ConnectionRequest };
}

function buildRDCleanPathResponse(serverAddr, x224Response, certChain) {
  const parts = [
    derWrapContext(0, derEncodeInteger(VERSION_1)),
    derWrapContext(6, derEncodeOctetString(x224Response)),
    derWrapContext(7, derWrap(TAG_SEQUENCE, Buffer.concat(certChain.map((c) => derEncodeOctetString(c))))),
    derWrapContext(9, derEncodeUtf8String(serverAddr)),
  ];
  return derWrap(TAG_SEQUENCE, Buffer.concat(parts));
}

function buildRDCleanPathError(errorCode, httpStatusCode) {
  const errParts = [derWrapContext(0, derEncodeInteger(errorCode))];
  if (httpStatusCode != null) {
    errParts.push(derWrapContext(1, derEncodeInteger(httpStatusCode)));
  }
  return derWrap(
    TAG_SEQUENCE,
    Buffer.concat([
      derWrapContext(0, derEncodeInteger(VERSION_1)),
      derWrapContext(1, derWrap(TAG_SEQUENCE, Buffer.concat(errParts))),
    ])
  );
}

function resolveTargetHostPort(destination) {
  let host = '127.0.0.1';
  let port = 3389;
  const clean = String(destination || '').trim();
  if (clean) {
    const idx = clean.lastIndexOf(':');
    if (idx > 0) {
      host = clean.slice(0, idx);
      port = parseInt(clean.slice(idx + 1), 10) || 3389;
    } else {
      host = clean;
    }
  }
  // Nếu client gửi IP LAN của chính máy PC này -> định tuyến thẳng vào 127.0.0.1:3389 siêu tốc
  const localIps = new Set(['localhost', '127.0.0.1']);
  const nets = os.networkInterfaces();
  for (const list of Object.values(nets)) {
    for (const iface of list || []) {
      if (iface && iface.address) localIps.add(iface.address);
    }
  }
  if (localIps.has(host)) {
    host = '127.0.0.1';
  }
  return { host, port };
}

function extractCertChain(peerCert) {
  const certs = [];
  if (!peerCert || !peerCert.raw) return certs;
  const seen = new Set();
  let cur = peerCert;
  while (cur && cur.raw) {
    const fp = cur.fingerprint256 || cur.raw.toString('hex');
    if (seen.has(fp)) break;
    seen.add(fp);
    certs.push(Buffer.from(cur.raw));
    if (cur.issuerCertificate && cur.issuerCertificate !== cur) {
      cur = cur.issuerCertificate;
    } else {
      break;
    }
  }
  return certs;
}

function performRDPHandshake(host, port, x224Request) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let rxBuf = Buffer.alloc(0);

    const tcpSocket = net.createConnection({ host, port }, () => {
      tcpSocket.setNoDelay(true);
      tcpSocket.write(x224Request);
    });

    const fail = (err) => {
      if (settled) return;
      settled = true;
      try { tcpSocket.destroy(); } catch (_) {}
      reject(err);
    };

    tcpSocket.on('error', (err) => fail(new Error(`TCP error: ${err.message}`)));
    tcpSocket.setTimeout(12000, () => fail(new Error('RDP handshake timeout')));

    const onData = (chunk) => {
      rxBuf = Buffer.concat([rxBuf, chunk]);
      if (rxBuf.length < 4) return;
      const expectedLen = (rxBuf[0] === 0x03 && rxBuf[1] === 0x00)
        ? ((rxBuf[2] << 8) | rxBuf[3])
        : rxBuf.length;
      if (rxBuf.length < expectedLen) return;

      const x224Response = Buffer.from(rxBuf.subarray(0, expectedLen));
      const extraBytes = rxBuf.subarray(expectedLen);

      tcpSocket.removeListener('data', onData);
      tcpSocket.removeAllListeners('error');
      tcpSocket.setTimeout(0);

      if (extraBytes.length > 0) {
        tcpSocket.unshift(extraBytes);
      }

      const tlsSocket = tls.connect(
        {
          socket: tcpSocket,
          rejectUnauthorized: false,
        },
        () => {
          if (settled) return;
          settled = true;
          tlsSocket.setNoDelay(true);
          const peerCert = tlsSocket.getPeerCertificate(true);
          const certChain = extractCertChain(peerCert);
          resolve({ x224Response, certChain, tlsSocket });
        }
      );

      tlsSocket.once('error', (err) => fail(new Error(`TLS error: ${err.message}`)));
    };

    tcpSocket.on('data', onData);
  });
}

// ── Minimalist Zero-Dependency RFC-6455 WebSocket Framing ──
function encodeWsFrame(payload, opcode = 0x02) {
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.allocUnsafe(2);
    header[0] = 0x80 | opcode;
    header[1] = len;
  } else if (len < 65536) {
    header = Buffer.allocUnsafe(4);
    header[0] = 0x80 | opcode;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.allocUnsafe(10);
    header[0] = 0x80 | opcode;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }
  return Buffer.concat([header, payload]);
}

class SimpleWebSocketConnection {
  constructor(socket, head) {
    this.socket = socket;
    this.open = true;
    this._rx = head && head.length > 0 ? Buffer.from(head) : Buffer.alloc(0);
    this._fragOpcode = 0;
    this._fragChunks = [];
    this.onBinaryMessage = null;
    this.onClose = null;

    socket.setNoDelay(true);
    socket.on('data', (chunk) => this._consume(chunk));
    socket.on('end', () => this._handleClose());
    socket.on('close', () => this._handleClose());
    socket.on('error', () => this._handleClose());

    if (this._rx.length > 0) {
      setImmediate(() => this._drainFrames());
    }
  }

  sendBinary(buf) {
    if (!this.open || this.socket.destroyed) return;
    try {
      this.socket.write(encodeWsFrame(buf, 0x02));
    } catch (_) {
      this.close();
    }
  }

  close() {
    if (!this.open) return;
    this.open = false;
    try {
      if (!this.socket.destroyed) {
        this.socket.write(encodeWsFrame(Buffer.alloc(0), 0x08));
        this.socket.end();
      }
    } catch (_) {}
    if (this.onClose) {
      const fn = this.onClose;
      this.onClose = null;
      fn();
    }
  }

  _handleClose() {
    if (!this.open) return;
    this.open = false;
    if (this.onClose) {
      const fn = this.onClose;
      this.onClose = null;
      fn();
    }
  }

  _consume(chunk) {
    this._rx = this._rx.length === 0 ? chunk : Buffer.concat([this._rx, chunk]);
    this._drainFrames();
  }

  _drainFrames() {
    while (this.open && this._rx.length >= 2) {
      const b0 = this._rx[0];
      const b1 = this._rx[1];
      const fin = (b0 & 0x80) !== 0;
      const opcode = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let payloadLen = b1 & 0x7f;
      let offset = 2;

      if (payloadLen === 126) {
        if (this._rx.length < 4) return;
        payloadLen = this._rx.readUInt16BE(2);
        offset = 4;
      } else if (payloadLen === 127) {
        if (this._rx.length < 10) return;
        payloadLen = Number(this._rx.readBigUInt64BE(2));
        offset = 10;
      }

      const maskLen = masked ? 4 : 0;
      if (this._rx.length < offset + maskLen + payloadLen) return;

      const payload = Buffer.from(this._rx.subarray(offset + maskLen, offset + maskLen + payloadLen));
      if (masked) {
        const mask = this._rx.subarray(offset, offset + 4);
        for (let i = 0; i < payload.length; i++) {
          payload[i] ^= mask[i & 3];
        }
      }

      this._rx = this._rx.subarray(offset + maskLen + payloadLen);

      if (opcode === 0x08) {
        this.close();
        return;
      }
      if (opcode === 0x09) {
        // Ping -> Pong
        if (!this.socket.destroyed) {
          this.socket.write(encodeWsFrame(payload, 0x0a));
        }
        continue;
      }
      if (opcode === 0x0a) continue;

      if (opcode === 0x00) {
        this._fragChunks.push(payload);
        if (fin) {
          const full = Buffer.concat(this._fragChunks);
          this._fragChunks = [];
          if (this.onBinaryMessage) this.onBinaryMessage(full);
        }
      } else if (opcode === 0x01 || opcode === 0x02) {
        if (fin) {
          if (this.onBinaryMessage) this.onBinaryMessage(payload);
        } else {
          this._fragOpcode = opcode;
          this._fragChunks = [payload];
        }
      }
    }
  }
}

function handleRdpWebSocket(wsConn) {
  let tlsSocket = null;
  let handshakeDone = false;

  wsConn.onBinaryMessage = async (data) => {
    if (!handshakeDone) {
      wsConn.onBinaryMessage = null;
      try {
        const req = parseRDCleanPathRequest(data);
        const { host, port } = resolveTargetHostPort(req.destination);
        const res = await performRDPHandshake(host, port, req.x224ConnectionRequest);
        tlsSocket = res.tlsSocket;
        handshakeDone = true;

        const pdu = buildRDCleanPathResponse(`${host}:${port}`, res.x224Response, res.certChain);
        wsConn.sendBinary(pdu);

        tlsSocket.on('data', (chunk) => {
          wsConn.sendBinary(chunk);
        });
        tlsSocket.on('end', () => wsConn.close());
        tlsSocket.on('close', () => wsConn.close());
        tlsSocket.on('error', () => wsConn.close());

        wsConn.onBinaryMessage = (clientChunk) => {
          if (tlsSocket && !tlsSocket.destroyed) {
            tlsSocket.write(clientChunk);
          }
        };
      } catch (err) {
        try {
          wsConn.sendBinary(buildRDCleanPathError(1, 502));
        } catch (_) {}
        wsConn.close();
      }
    }
  };

  wsConn.onClose = () => {
    if (tlsSocket && !tlsSocket.destroyed) {
      try { tlsSocket.destroy(); } catch (_) {}
    }
  };
}

function getLanIps() {
  const ips = [];
  const nets = os.networkInterfaces();
  for (const [name, list] of Object.entries(nets)) {
    for (const iface of list || []) {
      if (iface.family === 'IPv4' && !iface.internal) {
        ips.push({ name, ip: iface.address });
      }
    }
  }
  return ips;
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }
  if (req.url && req.url.startsWith('/health')) {
    const payload = JSON.stringify({
      ok: true,
      service: 'pc-rdp-gateway',
      version: '2.1.1',
      hostname: os.hostname(),
      default_user: `${os.hostname()}\\${os.userInfo().username}`,
      port: LISTEN_PORT,
      ips: getLanIps(),
    });
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(payload);
    return;
  }
  res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Windows PC Remote RDP Gateway Running.\n');
});

server.on('error', (err) => {
  if (err && err.code === 'EADDRINUSE') {
    console.log(`[PC-RDP-Gateway] Port ${LISTEN_PORT} is already active.`);
    process.exit(0);
  }
  console.error('[PC-RDP-Gateway] Server error:', err);
  process.exit(1);
});

server.on('upgrade', (req, socket, head) => {
  const key = req.headers['sec-websocket-key'];
  if (!key) {
    socket.destroy();
    return;
  }
  const accept = crypto
    .createHash('sha1')
    .update(key + WS_MAGIC_GUID)
    .digest('base64');

  const protoHeader = req.headers['sec-websocket-protocol'];
  const headers = [
    'HTTP/1.1 101 Switching Protocols',
    'Upgrade: websocket',
    'Connection: Upgrade',
    `Sec-WebSocket-Accept: ${accept}`,
  ];
  if (protoHeader) {
    const firstProto = String(protoHeader).split(',')[0].trim();
    if (firstProto) headers.push(`Sec-WebSocket-Protocol: ${firstProto}`);
  }
  headers.push('', '');
  socket.write(headers.join('\r\n'));

  const wsConn = new SimpleWebSocketConnection(socket, head);
  handleRdpWebSocket(wsConn);
});

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  const ips = getLanIps().map((x) => `${x.ip}:${LISTEN_PORT}`).join(', ');
  console.log(`[PC-RDP-Gateway] Listening on ${LISTEN_HOST}:${LISTEN_PORT} (${ips})`);
});
