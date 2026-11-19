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
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

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
          try { tcpSocket.setKeepAlive(true, 15000); } catch (_) {}
          try { tlsSocket.setKeepAlive(true, 15000); } catch (_) {}
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
    try { socket.setKeepAlive(true, 15000); } catch (_) {}
    this._pingTimer = setInterval(() => {
      if (!this.open || this.socket.destroyed) {
        clearInterval(this._pingTimer);
        this._pingTimer = null;
        return;
      }
      try {
        this.socket.write(encodeWsFrame(Buffer.alloc(0), 0x09));
      } catch (_) {}
    }, 18000);
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

  sendText(str) {
    if (!this.open || this.socket.destroyed) return;
    try {
      this.socket.write(encodeWsFrame(Buffer.from(String(str), 'utf-8'), 0x01));
    } catch (_) {
      this.close();
    }
  }

  close() {
    if (!this.open) return;
    this.open = false;
    if (this._pingTimer) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
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
    if (this._pingTimer) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
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

// ── RDP Audio Bridge (MS-RDPSND Loa Stereo + MS-RDPEAI Microphone "Remote Audio") ──
const audioSessions = new Map();

function getOrCreateAudioSession(sid) {
  if (!sid) return null;
  let sess = audioSessions.get(sid);
  if (!sess) {
    sess = new RdpAudioSession(sid);
    audioSessions.set(sid, sess);
  }
  return sess;
}

function encodeDvcId(id, cbId) {
  if (cbId === 0) return Buffer.from([id & 0xff]);
  if (cbId === 1) {
    const b = Buffer.allocUnsafe(2);
    b.writeUInt16LE(id & 0xffff, 0);
    return b;
  }
  const b = Buffer.allocUnsafe(4);
  b.writeUInt32LE(id >>> 0, 0);
  return b;
}

function decodeDvcId(buf, offset, cbId) {
  if (cbId === 0) return { id: buf[offset], bytes: 1 };
  if (cbId === 1) return { id: buf.readUInt16LE(offset), bytes: 2 };
  return { id: buf.readUInt32LE(offset), bytes: 4 };
}

class RdpAudioSession {
  constructor(sid) {
    this.sid = sid;
    this.tlsSocket = null;
    this.audioWs = null;
    this.clientStreamBuf = Buffer.alloc(0);
    this.serverStreamBuf = Buffer.alloc(0);

    this.csNetNames = [];
    this.ioChanId = null;
    this.rdpsndChanId = null;
    this.drdynvcChanId = null;
    this.mcsInitiator = null;
    this.patchedClientInfo = false;
    this.gotRdpsndWave = false;

    this.rdpsndVcBuf = Buffer.alloc(0);
    this.pendingLegacyWave = null;
    this.spkFormat = null;

    this.drdynvcVcBuf = Buffer.alloc(0);
    this.drdynvcRawPkts = [];
    this.audinDvcId = null;
    this.audinCbId = 0;
    this.audinFragBuf = Buffer.alloc(0);
    this.audinExpectedLen = 0;
    this.audinOpen = false;
    this.micSpec = null;
  }

  attachTls(tlsSocket) {
    this.tlsSocket = tlsSocket;
  }

  attachAudioWs(wsConn) {
    this.audioWs = wsConn;
    syncWasapiProcess();
    if (this.spkFormat) {
      wsConn.sendText(JSON.stringify({ type: 'spk_format', ...this.spkFormat }));
    } else if (wasapiFormat) {
      wsConn.sendText(JSON.stringify({ type: 'spk_format', ...wasapiFormat }));
    }
    if (this.audinOpen && this.micSpec) {
      wsConn.sendText(JSON.stringify({ type: 'mic_start', ...this.micSpec }));
    }
    wsConn.onBinaryMessage = (data) => {
      if (!data || data.length < 2) return;
      if (data[0] === 0x02) {
        this.forwardMicPcmToServer(data.subarray(1));
      }
    };
    wsConn.onClose = () => {
      if (this.audioWs === wsConn) this.audioWs = null;
      syncWasapiProcess();
    };
  }

  destroy() {
    if (this.audioWs) {
      const a = this.audioWs;
      this.audioWs = null;
      try { a.close(); } catch (_) {}
    }
    audioSessions.delete(this.sid);
    syncWasapiProcess();
  }

  sendToTlsVc(channelId, vcPayload) {
    if (!this.tlsSocket || this.tlsSocket.destroyed || this.mcsInitiator === null || !channelId) {
      return;
    }
    const CHUNK_MAX = 1600;
    const totalLen = vcPayload.length;
    let offset = 0;
    while (offset < totalLen || (totalLen === 0 && offset === 0)) {
      const end = Math.min(totalLen, offset + CHUNK_MAX);
      const chunk = vcPayload.subarray(offset, end);
      let flags = 0;
      if (offset === 0) flags |= 0x01;
      if (end >= totalLen) flags |= 0x02;

      const vcPdu = Buffer.allocUnsafe(8 + chunk.length);
      vcPdu.writeUInt32LE(totalLen, 0);
      vcPdu.writeUInt32LE(flags, 4);
      chunk.copy(vcPdu, 8);

      const perLen = vcPdu.length < 0x80
        ? Buffer.from([vcPdu.length])
        : Buffer.from([0x80 | (vcPdu.length >> 8), vcPdu.length & 0xff]);

      const mcsHdr = Buffer.allocUnsafe(6);
      mcsHdr[0] = 0x64; // SendDataRequest
      mcsHdr.writeUInt16BE(this.mcsInitiator, 1);
      mcsHdr.writeUInt16BE(channelId, 3);
      mcsHdr[5] = 0x70;

      const tpktLen = 4 + 3 + mcsHdr.length + perLen.length + vcPdu.length;
      const pkt = Buffer.concat([
        Buffer.from([0x03, 0x00, (tpktLen >> 8) & 0xff, tpktLen & 0xff, 0x02, 0xf0, 0x80]),
        mcsHdr,
        perLen,
        vcPdu,
      ]);
      try {
        this.tlsSocket.write(pkt);
      } catch (_) {}

      offset = end;
      if (totalLen === 0) break;
    }
  }

  sendAudinDvcData(payload) {
    if (this.audinDvcId === null || !this.drdynvcChanId) return;
    const idBuf = encodeDvcId(this.audinDvcId, this.audinCbId);
    const MAX_FIRST = 1580;
    if (payload.length <= MAX_FIRST) {
      const hdr = Buffer.from([(0x03 << 4) | (this.audinCbId & 0x03)]);
      this.sendToTlsVc(this.drdynvcChanId, Buffer.concat([hdr, idBuf, payload]));
      return;
    }
    const lenBuf = Buffer.allocUnsafe(2);
    lenBuf.writeUInt16LE(payload.length, 0);
    const firstHdr = Buffer.from([(0x02 << 4) | (0x01 << 2) | (this.audinCbId & 0x03)]);
    this.sendToTlsVc(
      this.drdynvcChanId,
      Buffer.concat([firstHdr, idBuf, lenBuf, payload.subarray(0, MAX_FIRST)])
    );
    let off = MAX_FIRST;
    while (off < payload.length) {
      const nextSlice = payload.subarray(off, Math.min(payload.length, off + MAX_FIRST));
      const dataHdr = Buffer.from([(0x03 << 4) | (this.audinCbId & 0x03)]);
      this.sendToTlsVc(this.drdynvcChanId, Buffer.concat([dataHdr, idBuf, nextSlice]));
      off += nextSlice.length;
    }
  }

  forwardMicPcmToServer(pcmBytes) {
    if (!this.audinOpen || this.audinDvcId === null || !pcmBytes || pcmBytes.length === 0) return;
    this.sendAudinDvcData(Buffer.from([0x05])); // MSG_SNDIN_DATA_INCOMING
    const dataPdu = Buffer.allocUnsafe(1 + pcmBytes.length);
    dataPdu[0] = 0x06; // MSG_SNDIN_DATA
    pcmBytes.copy(dataPdu, 1);
    this.sendAudinDvcData(dataPdu);
  }

  _extractNextRdpPdu(buf, preMcs = false) {
    if (buf.length < 2) return null;
    if ((buf[0] & 0x03) === 0x03 && buf[0] === 0x03) {
      if (buf.length < 4) return null;
      if (buf[1] === 0x00) {
        const len = (buf[2] << 8) | buf[3];
        if (len < 4) return { pkt: buf, rest: Buffer.alloc(0) };
        if (buf.length < len) return null;
        return { pkt: Buffer.from(buf.subarray(0, len)), rest: buf.subarray(len) };
      }
    }
    if (preMcs) {
      if (buf[0] === 0x30) {
        const b1 = buf[1];
        let len = 0;
        if ((b1 & 0x80) === 0) {
          len = 2 + b1;
        } else {
          const numOct = b1 & 0x7f;
          if (numOct === 0 || numOct > 4) return { pkt: buf, rest: Buffer.alloc(0) };
          if (buf.length < 2 + numOct) return null;
          let bodyLen = 0;
          for (let i = 0; i < numOct; i++) {
            bodyLen = (bodyLen << 8) | buf[2 + i];
          }
          len = 2 + numOct + bodyLen;
        }
        if (buf.length < len) return null;
        return { pkt: Buffer.from(buf.subarray(0, len)), rest: buf.subarray(len) };
      }
      return { pkt: buf, rest: Buffer.alloc(0) };
    }
    if ((buf[0] & 0x03) !== 0x00) {
      return { pkt: buf, rest: Buffer.alloc(0) };
    }
    const b1 = buf[1];
    let len = 0;
    if ((b1 & 0x80) === 0) {
      len = b1;
      if (len < 2) return { pkt: buf, rest: Buffer.alloc(0) };
    } else {
      if (buf.length < 3) return null;
      len = ((b1 & 0x7f) << 8) | buf[2];
      if (len < 3) return { pkt: buf, rest: Buffer.alloc(0) };
    }
    if (buf.length < len) return null;
    return { pkt: Buffer.from(buf.subarray(0, len)), rest: buf.subarray(len) };
  }

  processClientToServerChunk(chunk, writeToTls) {
    this.clientStreamBuf = this.clientStreamBuf.length === 0
      ? chunk
      : Buffer.concat([this.clientStreamBuf, chunk]);

    while (this.clientStreamBuf.length > 0) {
      const parsed = this._extractNextRdpPdu(this.clientStreamBuf, this.csNetNames.length === 0);
      if (!parsed) break;
      this.clientStreamBuf = parsed.rest;
      const pkt = parsed.pkt;

      if (pkt[0] === 0x03 && pkt.length >= 14 && pkt[4] === 0x02 && pkt[5] === 0xf0 && pkt[6] === 0x80) {
        if (this.csNetNames.length === 0 && pkt[7] === 0x7f && pkt[8] === 0x65) {
          this._scanCsNetAndDisableAudioCompression(pkt);
        } else if ((pkt[7] >> 2) === 25 && pkt.length >= 15) {
          this.mcsInitiator = pkt.readUInt16BE(8);
          const chanId = pkt.readUInt16BE(10);
          if (this.rdpsndChanId !== null && chanId === this.rdpsndChanId) {
            continue; // Chặn phản hồi rỗng của NoopRdpsndBackend
          }
          if (!this.patchedClientInfo && (this.ioChanId === null || chanId === this.ioChanId)) {
            const secOff = (pkt[13] & 0x80) !== 0 ? 15 : 14;
            if (pkt.length >= secOff + 12) {
              const secFlags = pkt.readUInt16LE(secOff);
              if ((secFlags & 0x0040) !== 0 && (secFlags & 0x0080) === 0) {
                const oldFlags = pkt.readUInt32LE(secOff + 8);
                if ((oldFlags & 0x00000011) !== 0) {
                  const newFlags = ((oldFlags & ~0x00080000) | 0x00200000) >>> 0;
                  pkt.writeUInt32LE(newFlags, secOff + 8);
                  this.patchedClientInfo = true;
                }
              }
            }
          }
        }
      }
      writeToTls(pkt);
    }
  }

  processServerToClientChunk(chunk, writeToClient) {
    this.serverStreamBuf = this.serverStreamBuf.length === 0
      ? chunk
      : Buffer.concat([this.serverStreamBuf, chunk]);

    while (this.serverStreamBuf.length > 0) {
      const parsed = this._extractNextRdpPdu(this.serverStreamBuf, this.csNetNames.length === 0);
      if (!parsed) break;
      this.serverStreamBuf = parsed.rest;
      const pkt = parsed.pkt;

      if (pkt[0] === 0x03 && pkt.length >= 14 && pkt[4] === 0x02 && pkt[5] === 0xf0 && pkt[6] === 0x80) {
        if (this.csNetNames.length > 0 && this.rdpsndChanId === null && pkt[7] === 0x7f && pkt[8] === 0x66) {
          this._scanScNet(pkt);
        } else if ((pkt[7] >> 2) === 26 && pkt.length >= 16) {
          const chanId = pkt.readUInt16BE(10);
          if (this.rdpsndChanId !== null && chanId === this.rdpsndChanId) {
            this._handleRdpsndPacket(pkt);
            continue;
          }
          if (this.drdynvcChanId !== null && chanId === this.drdynvcChanId) {
            const forwardPkts = this._handleDrdynvcPacket(pkt);
            for (const fp of forwardPkts) writeToClient(fp);
            continue;
          }
        }
      }
      writeToClient(pkt);
    }
  }

  _scanCsNetAndDisableAudioCompression(pkt) {
    for (let pos = 12; pos + 20 <= pkt.length; pos++) {
      if (pkt[pos] === 0x03 && pkt[pos + 1] === 0xc0) {
        const blockLen = pkt.readUInt16LE(pos + 2);
        const count = pkt.readUInt32LE(pos + 4);
        if (count >= 1 && count <= 31 && blockLen === 8 + count * 12 && pos + blockLen <= pkt.length) {
          const names = [];
          for (let i = 0; i < count; i++) {
            const cOff = pos + 8 + i * 12;
            const rawName = pkt.subarray(cOff, cOff + 8).toString('ascii').replace(/\0+$/, '').toLowerCase();
            names.push(rawName);
            if (rawName === 'rdpsnd' || rawName === 'drdynvc') {
              const opts = pkt.readUInt32LE(cOff + 8);
              pkt.writeUInt32LE((opts & ~0x00c00000) >>> 0, cOff + 8);
            }
          }
          this.csNetNames = names;
          return;
        }
      }
    }
  }

  _scanScNet(pkt) {
    const n = this.csNetNames.length;
    if (n === 0) return;
    const expectedPad = (n % 2 === 1) ? 2 : 0;
    for (let pos = 12; pos + 8 + n * 2 <= pkt.length; pos++) {
      if (pkt[pos] === 0x03 && pkt[pos + 1] === 0x0c) {
        const blockLen = pkt.readUInt16LE(pos + 2);
        const ioChan = pkt.readUInt16LE(pos + 4);
        const count = pkt.readUInt16LE(pos + 6);
        if (
          count === n &&
          ioChan >= 1000 &&
          ioChan <= 1100 &&
          (blockLen === 8 + n * 2 + expectedPad || blockLen === 8 + n * 2)
        ) {
          this.ioChanId = ioChan;
          for (let i = 0; i < count; i++) {
            const cid = pkt.readUInt16LE(pos + 8 + i * 2);
            if (this.csNetNames[i] === 'rdpsnd') this.rdpsndChanId = cid;
            if (this.csNetNames[i] === 'drdynvc') this.drdynvcChanId = cid;
          }
          return;
        }
      }
    }
  }

  _parseVcChunk(pkt) {
    let vcOff = 14;
    if ((pkt[13] & 0x80) !== 0) vcOff = 15;
    if (pkt.length < vcOff + 8) return null;
    const vcFlags = pkt.readUInt32LE(vcOff + 4);
    const vcChunk = pkt.subarray(vcOff + 8);
    return { vcFlags, vcChunk };
  }

  _handleRdpsndPacket(pkt) {
    const parsed = this._parseVcChunk(pkt);
    if (!parsed) return;
    if (parsed.vcFlags & 0x01) {
      this.rdpsndVcBuf = Buffer.from(parsed.vcChunk);
    } else {
      this.rdpsndVcBuf = Buffer.concat([this.rdpsndVcBuf, parsed.vcChunk]);
    }
    if (!(parsed.vcFlags & 0x02)) return;

    const pdu = this.rdpsndVcBuf;
    this.rdpsndVcBuf = Buffer.alloc(0);
    if (pdu.length < 4) return;

    if (this.pendingLegacyWave) {
      const pw = this.pendingLegacyWave;
      this.pendingLegacyWave = null;
      const pcm = Buffer.concat([pw.first4, pdu.subarray(Math.min(4, pdu.length))]);
      this._sendWaveConfirm(pw.ts, pw.blockNo);
      this._pushSpeakerPcm(pcm);
      return;
    }

    const msgType = pdu[0];
    if (msgType === 0x07 && pdu.length >= 24) {
      const numFmt = pdu.readUInt16LE(18);
      const srvVer = pdu.readUInt16LE(21);
      let off = 24;
      let chosen = null;
      for (let i = 0; i < numFmt && off + 18 <= pdu.length; i++) {
        const tag = pdu.readUInt16LE(off);
        const ch = pdu.readUInt16LE(off + 2);
        const rate = pdu.readUInt32LE(off + 4);
        const bits = pdu.readUInt16LE(off + 14);
        const cbSize = pdu.readUInt16LE(off + 16);
        if (tag === 1 && bits === 16 && (ch === 2 || ch === 1)) {
          if (!chosen || (ch === 2 && chosen.ch < 2) || (rate >= 44100 && chosen.rate < 44100)) {
            chosen = { ch, rate, bits: 16 };
          }
        }
        off += 18 + cbSize;
      }
      if (!chosen) chosen = { ch: 2, rate: 44100, bits: 16 };
      this.spkFormat = { rate: chosen.rate, channels: chosen.ch };

      const fmt18 = Buffer.allocUnsafe(18);
      fmt18.writeUInt16LE(1, 0);
      fmt18.writeUInt16LE(chosen.ch, 2);
      fmt18.writeUInt32LE(chosen.rate, 4);
      fmt18.writeUInt32LE(chosen.rate * chosen.ch * 2, 8);
      fmt18.writeUInt16LE(chosen.ch * 2, 12);
      fmt18.writeUInt16LE(16, 14);
      fmt18.writeUInt16LE(0, 16);

      const resp = Buffer.allocUnsafe(24 + 18);
      resp[0] = 0x07;
      resp[1] = 0x00;
      resp.writeUInt16LE(20 + 18, 2);
      resp.writeUInt32LE(0x00000003, 4); // TSSNDCAPS_ALIVE | TSSNDCAPS_VOLUME
      resp.writeUInt32LE(0xffffffff, 8);
      resp.writeUInt32LE(0, 12);
      resp.writeUInt16LE(0, 16);
      resp.writeUInt16LE(1, 18);
      resp[20] = 0;
      resp.writeUInt16LE(Math.min(Math.max(srvVer, 2), 6), 21);
      resp[23] = 0;
      fmt18.copy(resp, 24);
      this.sendToTlsVc(this.rdpsndChanId, resp);

      if (srvVer >= 6) {
        const qm = Buffer.from([0x0c, 0x00, 0x04, 0x00, 0x02, 0x00, 0x00, 0x00]);
        this.sendToTlsVc(this.rdpsndChanId, qm);
      }
      if (this.audioWs) {
        this.audioWs.sendText(JSON.stringify({ type: 'spk_format', ...this.spkFormat }));
      }
    } else if (msgType === 0x06 && pdu.length >= 8) {
      const confirm = Buffer.from([0x06, 0x00, 0x04, 0x00, pdu[4], pdu[5], pdu[6], pdu[7]]);
      this.sendToTlsVc(this.rdpsndChanId, confirm);
    } else if (msgType === 0x0d && pdu.length >= 16) {
      const ts = pdu.readUInt16LE(4);
      const blockNo = pdu[8];
      const pcm = pdu.subarray(16);
      this._sendWaveConfirm(ts, blockNo);
      this._pushSpeakerPcm(pcm);
    } else if (msgType === 0x02 && pdu.length >= 16) {
      const ts = pdu.readUInt16LE(4);
      const blockNo = pdu[8];
      const first4 = Buffer.from(pdu.subarray(12, 16));
      this.pendingLegacyWave = { ts, blockNo, first4 };
    }
  }

  _sendWaveConfirm(ts, blockNo) {
    const c = Buffer.allocUnsafe(8);
    c[0] = 0x05;
    c[1] = 0x00;
    c.writeUInt16LE(4, 2);
    c.writeUInt16LE(ts & 0xffff, 4);
    c[6] = blockNo & 0xff;
    c[7] = 0x00;
    this.sendToTlsVc(this.rdpsndChanId, c);
  }

  _pushSpeakerPcm(pcm) {
    if (!this.audioWs || !pcm || pcm.length === 0) return;
    this.gotRdpsndWave = true;
    const out = Buffer.allocUnsafe(1 + pcm.length);
    out[0] = 0x01;
    pcm.copy(out, 1);
    this.audioWs.sendBinary(out);
  }

  _handleDrdynvcPacket(pkt) {
    const parsed = this._parseVcChunk(pkt);
    if (!parsed) return [pkt];
    if (parsed.vcFlags & 0x01) {
      this.drdynvcVcBuf = Buffer.from(parsed.vcChunk);
      this.drdynvcRawPkts = [pkt];
    } else {
      this.drdynvcVcBuf = Buffer.concat([this.drdynvcVcBuf, parsed.vcChunk]);
      this.drdynvcRawPkts.push(pkt);
    }
    if (!(parsed.vcFlags & 0x02)) return [];

    const dvc = this.drdynvcVcBuf;
    const rawPkts = this.drdynvcRawPkts;
    this.drdynvcVcBuf = Buffer.alloc(0);
    this.drdynvcRawPkts = [];

    if (dvc.length < 2) return rawPkts;
    const cmd = (dvc[0] >> 4) & 0x0f;
    const spOrLen = (dvc[0] >> 2) & 0x03;
    const cbId = dvc[0] & 0x03;
    if (cbId === 3) return rawPkts;
    const idLen = cbId === 0 ? 1 : (cbId === 1 ? 2 : 4);
    if (dvc.length < 1 + idLen) return rawPkts;
    const { id: dvcChanId } = decodeDvcId(dvc, 1, cbId);

    if (cmd === 0x01) {
      const nameSlice = dvc.subarray(1 + idLen);
      const nulIdx = nameSlice.indexOf(0);
      const chName = (nulIdx >= 0 ? nameSlice.subarray(0, nulIdx) : nameSlice).toString('ascii');
      if (chName === 'AUDIO_INPUT') {
        this.audinDvcId = dvcChanId;
        this.audinCbId = cbId;
        this.audinExpectedLen = 0;
        this.audinFragBuf = Buffer.alloc(0);
        const rsp = Buffer.concat([
          Buffer.from([(0x01 << 4) | cbId]),
          encodeDvcId(dvcChanId, cbId),
          Buffer.from([0x00, 0x00, 0x00, 0x00]),
        ]);
        this.sendToTlsVc(this.drdynvcChanId, rsp);
        return [];
      }
      return rawPkts;
    }

    if (this.audinDvcId !== null && dvcChanId === this.audinDvcId) {
      if (cmd === 0x04) {
        const cls = Buffer.concat([
          Buffer.from([(0x04 << 4) | cbId]),
          encodeDvcId(dvcChanId, cbId),
        ]);
        this.sendToTlsVc(this.drdynvcChanId, cls);
        this.audinOpen = false;
        this.audinDvcId = null;
        if (this.audioWs) this.audioWs.sendText('{"type":"mic_stop"}');
        return [];
      }
      if (cmd === 0x02) {
        const lenBytes = spOrLen === 0 ? 1 : (spOrLen === 1 ? 2 : 4);
        if (dvc.length < 1 + idLen + lenBytes) return [];
        const totalLen = lenBytes === 1
          ? dvc[1 + idLen]
          : (lenBytes === 2 ? dvc.readUInt16LE(1 + idLen) : dvc.readUInt32LE(1 + idLen));
        this.audinExpectedLen = totalLen;
        this.audinFragBuf = Buffer.from(dvc.subarray(1 + idLen + lenBytes));
        if (this.audinFragBuf.length >= this.audinExpectedLen) {
          const full = this.audinFragBuf.subarray(0, this.audinExpectedLen);
          this.audinExpectedLen = 0;
          this.audinFragBuf = Buffer.alloc(0);
          this._handleAudinPdu(full);
        }
        return [];
      }
      if (cmd === 0x03) {
        const body = dvc.subarray(1 + idLen);
        if (this.audinExpectedLen > 0) {
          this.audinFragBuf = Buffer.concat([this.audinFragBuf, body]);
          if (this.audinFragBuf.length >= this.audinExpectedLen) {
            const full = this.audinFragBuf.subarray(0, this.audinExpectedLen);
            this.audinExpectedLen = 0;
            this.audinFragBuf = Buffer.alloc(0);
            this._handleAudinPdu(full);
          }
        } else {
          this._handleAudinPdu(body);
        }
        return [];
      }
      return [];
    }

    return rawPkts;
  }

  _handleAudinPdu(msg) {
    if (!msg || msg.length < 1) return;
    const msgId = msg[0];
    if (msgId === 0x01 && msg.length >= 5) {
      const srvVer = msg.readUInt32LE(1);
      const reply = Buffer.allocUnsafe(5);
      reply[0] = 0x01;
      reply.writeUInt32LE(Math.min(Math.max(1, srvVer), 2), 1);
      this.sendAudinDvcData(reply);
    } else if (msgId === 0x02 && msg.length >= 9) {
      const numFmt = msg.readUInt32LE(1);
      let off = 9;
      let chosen = null;
      for (let i = 0; i < numFmt && off + 18 <= msg.length; i++) {
        const tag = msg.readUInt16LE(off);
        const ch = msg.readUInt16LE(off + 2);
        const rate = msg.readUInt32LE(off + 4);
        const bits = msg.readUInt16LE(off + 14);
        const cbSize = msg.readUInt16LE(off + 16);
        if (tag === 1 && bits === 16 && (ch === 1 || ch === 2)) {
          if (!chosen || (ch === 1 && chosen.ch > 1) || (rate >= 44100 && chosen.rate < 44100)) {
            chosen = { ch, rate, bits: 16 };
          }
        }
        off += 18 + cbSize;
      }
      if (!chosen) chosen = { ch: 1, rate: 44100, bits: 16 };

      const fmt18 = Buffer.allocUnsafe(18);
      fmt18.writeUInt16LE(1, 0);
      fmt18.writeUInt16LE(chosen.ch, 2);
      fmt18.writeUInt32LE(chosen.rate, 4);
      fmt18.writeUInt32LE(chosen.rate * chosen.ch * 2, 8);
      fmt18.writeUInt16LE(chosen.ch * 2, 12);
      fmt18.writeUInt16LE(16, 14);
      fmt18.writeUInt16LE(0, 16);

      const reply = Buffer.allocUnsafe(9 + 18);
      reply[0] = 0x02;
      reply.writeUInt32LE(1, 1);
      reply.writeUInt32LE(9 + 18, 5);
      fmt18.copy(reply, 9);
      this.sendAudinDvcData(reply);
    } else if (msgId === 0x03 && msg.length >= 27) {
      const framesPerPacket = msg.readUInt32LE(1) || 480;
      const initialFormat = msg.readUInt32LE(5);
      const ch = msg.readUInt16LE(11) || 1;
      const rate = msg.readUInt32LE(13) || 44100;

      const fmtChg = Buffer.allocUnsafe(5);
      fmtChg[0] = 0x07;
      fmtChg.writeUInt32LE(initialFormat, 1);
      this.sendAudinDvcData(fmtChg);

      const openReply = Buffer.from([0x04, 0x00, 0x00, 0x00, 0x00]);
      this.sendAudinDvcData(openReply);

      this.audinOpen = true;
      this.micSpec = { rate, channels: ch, framesPerPacket };
      if (this.audioWs) {
        this.audioWs.sendText(JSON.stringify({ type: 'mic_start', ...this.micSpec }));
      }
    } else if (msgId === 0x07 && msg.length >= 5) {
      const fmtChg = Buffer.from(msg.subarray(0, 5));
      this.sendAudinDvcData(fmtChg);
    }
  }
}

function handleRdpWebSocket(wsConn, sid) {
  let tlsSocket = null;
  let handshakeDone = false;
  const audioSess = getOrCreateAudioSession(sid);

  wsConn.onBinaryMessage = async (data) => {
    if (!handshakeDone) {
      wsConn.onBinaryMessage = null;
      try {
        const req = parseRDCleanPathRequest(data);
        const { host, port } = resolveTargetHostPort(req.destination);
        const res = await performRDPHandshake(host, port, req.x224ConnectionRequest);
        tlsSocket = res.tlsSocket;
        handshakeDone = true;
        if (audioSess) audioSess.attachTls(tlsSocket);

        const pdu = buildRDCleanPathResponse(`${host}:${port}`, res.x224Response, res.certChain);
        wsConn.sendBinary(pdu);

        tlsSocket.on('data', (chunk) => {
          if (audioSess) {
            audioSess.processServerToClientChunk(chunk, (outPkt) => wsConn.sendBinary(outPkt));
          } else {
            wsConn.sendBinary(chunk);
          }
        });
        tlsSocket.on('end', () => wsConn.close());
        tlsSocket.on('close', () => wsConn.close());
        tlsSocket.on('error', () => wsConn.close());

        wsConn.onBinaryMessage = (clientChunk) => {
          if (!tlsSocket || tlsSocket.destroyed) return;
          if (audioSess) {
            audioSess.processClientToServerChunk(clientChunk, (outPkt) => {
              if (tlsSocket && !tlsSocket.destroyed) tlsSocket.write(outPkt);
            });
          } else {
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
    if (audioSess) audioSess.destroy();
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

const STATIC_DIR = path.resolve(__dirname, '..', 'static');
const RELEASES_DIR = path.resolve(__dirname, '..', 'releases');
let cachedWebBundle = null;
let cachedWebMtimes = '';

function getLiveWebBundle() {
  const idxPath = path.join(STATIC_DIR, 'index.html');
  const cssPath = path.join(STATIC_DIR, 'style.css');
  const jsPath = path.join(STATIC_DIR, 'app.js');
  const mKey = [
    fs.statSync(idxPath).mtimeMs,
    fs.statSync(cssPath).mtimeMs,
    fs.statSync(jsPath).mtimeMs,
  ].join(':');
  if (cachedWebBundle && cachedWebMtimes === mKey) {
    return cachedWebBundle;
  }
  const indexHtml = fs.readFileSync(idxPath, 'utf-8');
  const styleCss = fs.readFileSync(cssPath, 'utf-8');
  const appJs = fs.readFileSync(jsPath, 'utf-8');
  // Chống đẩy nhầm gói JS lỗi cú pháp khi đang sửa file giữa chừng
  try {
    new (require('vm').Script)(appJs, { filename: 'app.js' });
  } catch (syntaxErr) {
    if (cachedWebBundle) return cachedWebBundle;
    throw syntaxErr;
  }
  const verMatch = appJs.match(/const\s+BUNDLED_WEB_VERSION\s*=\s*"([^"]+)"/);
  const webVersion = verMatch ? verMatch[1] : '2.2.4';
  const etag = crypto
    .createHash('sha1')
    .update(indexHtml)
    .update('\n')
    .update(styleCss)
    .update('\n')
    .update(appJs)
    .digest('hex')
    .slice(0, 12);
  const bodyMatch = indexHtml.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  const rawBody = bodyMatch ? bodyMatch[1] : indexHtml;
  const bodyHtml = rawBody
    .replace(/<script[^>]*src=["'][^"']*app\.js[^"']*["'][^>]*>\s*<\/script>/gi, '')
    .trim();

  cachedWebMtimes = mKey;
  cachedWebBundle = {
    ok: true,
    web_version: webVersion,
    etag,
    body_html: bodyHtml,
    style_css: styleCss,
    app_js: appJs,
  };
  return cachedWebBundle;
}

const PREVIEW_HELPER_PORT = Number(process.env.PC_PREVIEW_PORT || 5052);
const CONSOLE_STREAMER_EXE = path.join(__dirname, 'pc_console_streamer.exe');
const pcParallelClients = new Set();

function tryStartConsoleStreamer() {
  if (!fs.existsSync(CONSOLE_STREAMER_EXE)) return;
  try {
    const p = spawn(CONSOLE_STREAMER_EXE, [], {
      detached: true,
      stdio: 'ignore',
    });
    p.unref();
  } catch (_) {}
}

function probeLocalPreviewHelper(cb) {
  let done = false;
  const finish = (val) => {
    if (done) return;
    done = true;
    cb(val);
  };
  const sock = net.createConnection({ host: '127.0.0.1', port: PREVIEW_HELPER_PORT });
  sock.setTimeout(360);
  let rx = '';
  sock.on('connect', () => {
    sock.write('PROBE\n');
  });
  sock.on('data', (chunk) => {
    rx += chunk.toString('utf8');
    const nl = rx.indexOf('\n');
    if (nl >= 0) {
      try {
        finish(JSON.parse(rx.slice(0, nl).trim()));
      } catch (_) {
        finish(null);
      }
      sock.destroy();
    }
  });
  sock.on('timeout', () => {
    finish(null);
    sock.destroy();
  });
  sock.on('error', () => {
    finish(null);
  });
  sock.on('close', () => {
    finish(null);
  });
}

function handlePcParallelWebSocket(wsConn) {
  const upstream = net.createConnection({ host: '127.0.0.1', port: PREVIEW_HELPER_PORT });
  upstream.setNoDelay(true);
  let rxBuf = Buffer.alloc(0);
  let closed = false;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    if (pcParallelClients.delete(wsConn)) {
      syncWasapiProcess();
    }
    try { upstream.destroy(); } catch (_) {}
    try { wsConn.close(); } catch (_) {}
  };

  upstream.on('connect', () => {
    pcParallelClients.add(wsConn);
    syncWasapiProcess();
    try {
      wsConn.sendText(JSON.stringify({ type: 'spk_format', ...wasapiFormat }));
    } catch (_) {}
    upstream.write('STREAM\n');
  });

  upstream.on('data', (chunk) => {
    rxBuf = rxBuf.length === 0 ? chunk : Buffer.concat([rxBuf, chunk]);
    while (rxBuf.length >= 4) {
      const fLen = rxBuf.readUInt32BE(0);
      if (fLen === 0 || fLen > 6 * 1024 * 1024) {
        cleanup();
        return;
      }
      if (rxBuf.length < 4 + fLen) break;
      const body = rxBuf.subarray(4, 4 + fLen);
      rxBuf = rxBuf.subarray(4 + fLen);
      if (body[0] === 0x20) {
        try {
          wsConn.sendText(body.subarray(1).toString('utf8'));
        } catch (_) {}
      } else {
        // Drop khung hình khi bộ đệm Wi-Fi đang nghẽn để thao tác luôn tức thì, không trễ dồn
        if (wsConn.socket && wsConn.socket.writableLength > 384 * 1024) {
          continue;
        }
        try {
          wsConn.sendBinary(body);
        } catch (_) {}
      }
    }
  });

  upstream.on('error', cleanup);
  upstream.on('close', cleanup);

  wsConn.onBinaryMessage = (payload) => {
    if (!closed && upstream.writable && payload && payload.length > 0) {
      const txt = payload.toString('utf8').replace(/[\r\n]+/g, ' ').trim();
      if (txt) {
        try { upstream.write(txt + '\n'); } catch (_) {}
      }
    }
  };
  wsConn.onClose = cleanup;
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }
  const rawUrlStr = String(req.url || '/');
  const cleanPath = rawUrlStr.split('?')[0];
  if (cleanPath === '/sync-ime') {
    let wantVn = true;
    try {
      const u = new URL(rawUrlStr, 'http://127.0.0.1');
      const vnParam = (u.searchParams.get('vn') || '1').trim().toLowerCase();
      wantVn = vnParam === '1' || vnParam === 'true' || vnParam === 'vn';
      const hintMacIp = (u.searchParams.get('mac_ip') || '').trim();
      const sockIp = String(req.socket && req.socket.remoteAddress ? req.socket.remoteAddress : '')
        .replace(/^::ffff:/, '')
        .trim();
      const learnedIp = hintMacIp || (sockIp && sockIp !== '127.0.0.1' && sockIp !== '::1' ? sockIp : '');
      if (learnedIp && /^\d+\.\d+\.\d+\.\d+$/.test(learnedIp)) {
        updateLearnedMacBridgeIp(learnedIp);
      }
    } catch (_) {}
    setWindowsUnikeyMode(wantVn);
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ ok: true, vn: wantVn }));
    return;
  }
  if (cleanPath === '/rdp-mode-check') {
    probeLocalPreviewHelper((info) => {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(
        JSON.stringify({
          ok: true,
          source: 'pc',
          parallel_available: Boolean(info && info.active),
          streamer_ready: Boolean(info && info.ok),
          window: info && info.active ? { width: info.width || 2248, height: info.height || 1080 } : null,
        })
      );
    });
    return;
  }
  if (cleanPath === '/health') {
    let webVer = '2.3.13';
    let etag = '';
    try {
      const b = getLiveWebBundle();
      webVer = b.web_version;
      etag = b.etag;
    } catch (_) {}
    const payload = JSON.stringify({
      ok: true,
      service: 'pc-rdp-gateway',
      version: '2.3.13',
      web_version: webVer,
      unikey_vn: lastUnikeyVnState,
      etag,
      hostname: os.hostname(),
      default_user: `${os.hostname()}\\${os.userInfo().username}`,
      port: LISTEN_PORT,
      ips: getLanIps(),
    });
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(payload);
    return;
  }
  if (cleanPath === '/web-manifest') {
    try {
      const b = getLiveWebBundle();
      let tagName = 'v2.1.4';
      try {
        const lj = JSON.parse(fs.readFileSync(path.join(RELEASES_DIR, 'latest.json'), 'utf-8'));
        if (lj && lj.tag_name) tagName = lj.tag_name;
      } catch (_) {}
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ ok: true, tag_name: tagName, web_version: b.web_version, etag: b.etag }));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ ok: false, error: String(err.message || err) }));
    }
    return;
  }
  if (cleanPath === '/web-bundle') {
    try {
      const b = getLiveWebBundle();
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(b));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ ok: false, error: String(err.message || err) }));
    }
    return;
  }
  if (cleanPath.startsWith('/static/')) {
    const rel = path.basename(cleanPath);
    if (['index.html', 'style.css', 'app.js', 'manifest.json'].includes(rel)) {
      const fp = path.join(STATIC_DIR, rel);
      if (fs.existsSync(fp)) {
        const mimes = {
          'index.html': 'text/html; charset=utf-8',
          'style.css': 'text/css; charset=utf-8',
          'app.js': 'application/javascript; charset=utf-8',
          'manifest.json': 'application/json; charset=utf-8',
        };
        res.writeHead(200, { 'Content-Type': mimes[rel] });
        res.end(fs.readFileSync(fp));
        return;
      }
    }
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
  const parsedUrl = new URL(req.url || '/', 'http://localhost');
  const sid = parsedUrl.searchParams.get('sid') || '';
  if (parsedUrl.pathname.startsWith('/rdp-parallel-ws')) {
    handlePcParallelWebSocket(wsConn);
    return;
  }
  if (parsedUrl.pathname.startsWith('/rdp-audio-ws')) {
    const sess = getOrCreateAudioSession(sid);
    if (sess) {
      sess.attachAudioWs(wsConn);
    } else {
      wsConn.close();
    }
    return;
  }
  handleRdpWebSocket(wsConn, sid);
});

// ── Bộ thu âm thanh hệ thống trực tiếp WASAPI Loopback + Đồng bộ UniKey [V]/[E] từ EVKey trên MacBook ──
const WASAPI_EXE = path.join(__dirname, 'pc_wasapi_loopback.exe');
const UNIKEY_SYNC_EXE = path.join(__dirname, 'pc_unikey_sync.exe');
let dynamicMacBridgeUrl = process.env.MAC_BRIDGE_URL || 'ws://192.168.52.103:5050/pc-bridge-ws';

let wasapiProc = null;
let wasapiRxBuf = Buffer.alloc(0);
let wasapiFormat = { rate: 44100, channels: 2 };
let macBridgeWs = null;
let macWantsAudio = false;

let unikeySyncProc = null;
let lastUnikeyVnState = null;

function ensureUnikeySyncWorker() {
  if (unikeySyncProc && !unikeySyncProc.killed) return unikeySyncProc;
  if (!fs.existsSync(UNIKEY_SYNC_EXE)) return null;
  try {
    const proc = spawn(UNIKEY_SYNC_EXE, [], {
      windowsHide: true,
      stdio: ['pipe', 'ignore', 'ignore'],
    });
    unikeySyncProc = proc;
    proc.on('exit', () => {
      if (unikeySyncProc === proc) unikeySyncProc = null;
    });
    proc.on('error', () => {
      if (unikeySyncProc === proc) unikeySyncProc = null;
    });
    return proc;
  } catch (_) {
    unikeySyncProc = null;
    return null;
  }
}

function setWindowsUnikeyMode(wantVn) {
  const flag = wantVn ? 1 : 0;
  lastUnikeyVnState = Boolean(wantVn);
  const proc = ensureUnikeySyncWorker();
  if (proc && proc.stdin && proc.stdin.writable) {
    try {
      proc.stdin.write(`${flag}\n`);
      return;
    } catch (_) {}
  }
  if (fs.existsSync(UNIKEY_SYNC_EXE)) {
    try {
      spawn(UNIKEY_SYNC_EXE, [String(flag)], { windowsHide: true, stdio: 'ignore' });
    } catch (_) {}
  }
}

function updateLearnedMacBridgeIp(ip) {
  const nextUrl = `ws://${ip}:5050/pc-bridge-ws`;
  if (nextUrl === dynamicMacBridgeUrl) return;
  dynamicMacBridgeUrl = nextUrl;
  if (!macBridgeWs || macBridgeWs.readyState !== 1) {
    if (macBridgeWs) {
      try { macBridgeWs.close(); } catch (_) {}
      macBridgeWs = null;
    }
    connectOutboundMacBridge();
  }
}

function hasLocalFallbackAudioListeners() {
  if (pcParallelClients.size > 0) return true;
  for (const sess of audioSessions.values()) {
    if (sess.audioWs && !sess.gotRdpsndWave) return true;
  }
  return false;
}

function broadcastWasapiFormat() {
  const fmtStr = JSON.stringify({ type: 'spk_format', ...wasapiFormat });
  if (macWantsAudio && macBridgeWs && macBridgeWs.readyState === 1) {
    try { macBridgeWs.send(fmtStr); } catch (_) {}
  }
  for (const ws of pcParallelClients) {
    try { ws.sendText(fmtStr); } catch (_) {}
  }
  for (const sess of audioSessions.values()) {
    if (sess.audioWs && !sess.gotRdpsndWave) {
      try { sess.audioWs.sendText(fmtStr); } catch (_) {}
    }
  }
}

function broadcastWasapiPcm(pcmChunk) {
  const needMac = macWantsAudio && macBridgeWs && macBridgeWs.readyState === 1;
  const needLocal = hasLocalFallbackAudioListeners();
  if (!needMac && !needLocal) return;
  const out = Buffer.allocUnsafe(1 + pcmChunk.length);
  out[0] = 0x01;
  pcmChunk.copy(out, 1);
  if (needMac) {
    try { macBridgeWs.send(out); } catch (_) {}
  }
  for (const ws of pcParallelClients) {
    try { ws.sendBinary(out); } catch (_) {}
  }
  if (needLocal) {
    for (const sess of audioSessions.values()) {
      if (sess.audioWs && !sess.gotRdpsndWave) {
        try { sess.audioWs.sendBinary(out); } catch (_) {}
      }
    }
  }
}

function syncWasapiProcess() {
  const want = macWantsAudio || hasLocalFallbackAudioListeners();
  if (!want) {
    if (wasapiProc) {
      try { wasapiProc.kill(); } catch (_) {}
      wasapiProc = null;
    }
    wasapiRxBuf = Buffer.alloc(0);
    return;
  }
  if (wasapiProc || !fs.existsSync(WASAPI_EXE)) return;

  wasapiRxBuf = Buffer.alloc(0);
  const proc = spawn(WASAPI_EXE, [], { windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
  wasapiProc = proc;

  proc.stdout.on('data', (chunk) => {
    wasapiRxBuf = wasapiRxBuf.length === 0 ? chunk : Buffer.concat([wasapiRxBuf, chunk]);
    while (wasapiRxBuf.length >= 2) {
      if (
        wasapiRxBuf.length >= 8 &&
        wasapiRxBuf[0] === 0x57 &&
        wasapiRxBuf[1] === 0x41 &&
        wasapiRxBuf[2] === 0x53 &&
        wasapiRxBuf[3] === 0x50
      ) {
        const rate = wasapiRxBuf.readUInt16LE(4) || 44100;
        const ch = wasapiRxBuf[6] || 2;
        wasapiFormat = { rate, channels: ch };
        wasapiRxBuf = wasapiRxBuf.subarray(8);
        broadcastWasapiFormat();
        continue;
      }
      if (wasapiRxBuf[0] === 0x57 && wasapiRxBuf.length < 8) break;

      const pcmLen = wasapiRxBuf.readUInt16LE(0);
      if (pcmLen === 0 || pcmLen > 16384) {
        wasapiRxBuf = Buffer.alloc(0);
        break;
      }
      if (wasapiRxBuf.length < 2 + pcmLen) break;
      const pcm = wasapiRxBuf.subarray(2, 2 + pcmLen);
      wasapiRxBuf = wasapiRxBuf.subarray(2 + pcmLen);
      broadcastWasapiPcm(pcm);
    }
  });

  proc.on('exit', () => {
    if (wasapiProc === proc) {
      wasapiProc = null;
      if (macWantsAudio) setTimeout(syncWasapiProcess, 800);
    }
  });
}

function connectOutboundMacBridge() {
  if (typeof WebSocket === 'undefined') return;
  if (macBridgeWs && (macBridgeWs.readyState === 0 || macBridgeWs.readyState === 1)) return;
  try {
    const ws = new WebSocket(dynamicMacBridgeUrl);
    macBridgeWs = ws;
    ws.onopen = () => {
      if (macWantsAudio) {
        syncWasapiProcess();
        broadcastWasapiFormat();
      }
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      try {
        const msg = JSON.parse(ev.data);
        if (msg.cmd === 'wasapi_start') {
          macWantsAudio = true;
          syncWasapiProcess();
          broadcastWasapiFormat();
        } else if (msg.cmd === 'wasapi_stop') {
          macWantsAudio = false;
          syncWasapiProcess();
        } else if (msg.cmd === 'sync_ime') {
          setWindowsUnikeyMode(Boolean(msg.vn));
        }
      } catch (_) {}
    };
    ws.onclose = () => {
      if (macBridgeWs === ws) macBridgeWs = null;
      macWantsAudio = false;
      syncWasapiProcess();
      setTimeout(connectOutboundMacBridge, 3500);
    };
    ws.onerror = () => {
      try { ws.close(); } catch (_) {}
    };
  } catch (_) {
    setTimeout(connectOutboundMacBridge, 4000);
  }
}

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  const ips = getLanIps().map((x) => `${x.ip}:${LISTEN_PORT}`).join(', ');
  console.log(`[PC-RDP-Gateway] Listening on ${LISTEN_HOST}:${LISTEN_PORT} (${ips})`);
  tryStartConsoleStreamer();
  connectOutboundMacBridge();
});
