"""Wire format. All multi-byte fields are network byte order (big endian)."""
import struct

MAGIC = b"RC"
HDR = struct.Struct("!2sBBIIIQ")  # magic, type, flags, session, seq, total, ts_us  (24 bytes)
HDR_LEN = HDR.size
IP_UDP_OVERHEAD = 28  # IPv4 (20) + UDP (8), used for on-the-wire byte accounting

DATA, REPAIR, HEARTBEAT, NACK, FIN, PROBE = 1, 2, 3, 4, 5, 6
NAMES = {DATA: "DATA", REPAIR: "REPAIR", HEARTBEAT: "HEARTBEAT", NACK: "NACK", FIN: "FIN", PROBE: "PROBE"}

_NACK_HEAD = struct.Struct("!IH")
_RANGE = struct.Struct("!II")
MAX_RANGES = 80


def pack(ptype, session, seq, total, ts_us, payload=b""):
    return HDR.pack(MAGIC, ptype, 0, session, seq, total, ts_us) + payload


def unpack(buf):
    """Return (type, session, seq, total, ts_us, payload) or None if not ours."""
    if len(buf) < HDR_LEN:
        return None
    magic, ptype, _flags, session, seq, total, ts_us = HDR.unpack_from(buf)
    if magic != MAGIC:
        return None
    return ptype, session, seq, total, ts_us, buf[HDR_LEN:]


def to_ranges(seqs):
    """Sorted iterable of ints -> list of inclusive (start, end) ranges."""
    out = []
    for s in sorted(seqs):
        if out and s == out[-1][1] + 1:
            out[-1][1] = s
        else:
            out.append([s, s])
    return [tuple(r) for r in out]


def pack_nack(rid, ranges):
    ranges = ranges[:MAX_RANGES]
    body = _NACK_HEAD.pack(rid, len(ranges)) + b"".join(_RANGE.pack(a, b) for a, b in ranges)
    return body


def unpack_nack(payload):
    rid, n = _NACK_HEAD.unpack_from(payload)
    ranges = [_RANGE.unpack_from(payload, _NACK_HEAD.size + i * _RANGE.size) for i in range(n)]
    return rid, ranges
