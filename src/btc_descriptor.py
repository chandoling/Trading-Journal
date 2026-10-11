from __future__ import annotations

import hashlib
import hmac
import re
import struct

import address_codec as ac

_RL = [list(range(16)),
       [7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8],
       [3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12],
       [1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2],
       [4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13]]
_RR = [[5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12],
       [6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2],
       [15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13],
       [8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14],
       [12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11]]
_SL = [[11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8],
       [7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12],
       [11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5],
       [11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12],
       [9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6]]
_SR = [[8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6],
       [9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11],
       [9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5],
       [15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8],
       [8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11]]
_KL = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
_KR = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]
_M32 = 0xFFFFFFFF


def _rol(x, n):
    return ((x << n) | (x >> (32 - n))) & _M32


def _rf(j, x, y, z):
    if j == 0:
        return x ^ y ^ z
    if j == 1:
        return (x & y) | (~x & z)
    if j == 2:
        return (x | ~y) ^ z
    if j == 3:
        return (x & z) | (y & ~z)
    return x ^ (y | ~z)


def ripemd160(data: bytes) -> bytes:
    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
    msg = bytes(data) + b"\x80" + b"\x00" * ((55 - len(data)) % 64) + struct.pack("<Q", (8 * len(data)) & 0xFFFFFFFFFFFFFFFF)
    for off in range(0, len(msg), 64):
        x = struct.unpack("<16I", msg[off:off + 64])
        al, bl, cl, dl, el = h
        ar, br, cr, dr, er = h
        for rnd in range(5):
            for i in range(16):
                t = (_rol((al + (_rf(rnd, bl, cl, dl) & _M32) + x[_RL[rnd][i]] + _KL[rnd]) & _M32, _SL[rnd][i]) + el) & _M32
                al, el, dl, cl, bl = el, dl, _rol(cl, 10), bl, t
                t = (_rol((ar + (_rf(4 - rnd, br, cr, dr) & _M32) + x[_RR[rnd][i]] + _KR[rnd]) & _M32, _SR[rnd][i]) + er) & _M32
                ar, er, dr, cr, br = er, dr, _rol(cr, 10), br, t
        t = (h[1] + cl + dr) & _M32
        h[1] = (h[2] + dl + er) & _M32
        h[2] = (h[3] + el + ar) & _M32
        h[3] = (h[4] + al + br) & _M32
        h[4] = (h[0] + bl + cr) & _M32
        h[0] = t
    return struct.pack("<5I", *h)


def hash160(b: bytes) -> bytes:
    return ripemd160(hashlib.sha256(b).digest())


P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _jadd(p, q):
    if p is None:
        return q
    if q is None:
        return p
    x1, y1, z1 = p
    x2, y2, z2 = q
    z1z1, z2z2 = z1 * z1 % P, z2 * z2 % P
    u1, u2 = x1 * z2z2 % P, x2 * z1z1 % P
    s1, s2 = y1 * z2 * z2z2 % P, y2 * z1 * z1z1 % P
    if u1 == u2:
        if s1 != s2:
            return None
        return _jdbl(p)
    h = (u2 - u1) % P
    r = (s2 - s1) % P
    hh = h * h % P
    hhh = h * hh % P
    v = u1 * hh % P
    x3 = (r * r - hhh - 2 * v) % P
    y3 = (r * (v - x3) - s1 * hhh) % P
    return (x3, y3, h * z1 * z2 % P)


def _jdbl(p):
    if p is None:
        return None
    x, y, z = p
    if y == 0:
        return None
    yy = y * y % P
    s = 4 * x * yy % P
    m = 3 * x * x % P
    x3 = (m * m - 2 * s) % P
    y3 = (m * (s - x3) - 8 * yy * yy) % P
    return (x3, y3, 2 * y * z % P)


def _affine(p):
    if p is None:
        return None
    x, y, z = p
    zi = pow(z, P - 2, P)
    zi2 = zi * zi % P
    return (x * zi2 % P, y * zi2 * zi % P)


_GTAB = []


def _g_table():
    if not _GTAB:
        q = (G[0], G[1], 1)
        for _ in range(256):
            _GTAB.append(q)
            q = _jdbl(q)
    return _GTAB


def point_mul_g(k: int):
    k %= N
    acc = None
    tab = _g_table()
    i = 0
    while k:
        if k & 1:
            acc = _jadd(acc, tab[i])
        k >>= 1
        i += 1
    return _affine(acc)


def point_add(a, b):
    ja = None if a is None else (a[0], a[1], 1)
    jb = None if b is None else (b[0], b[1], 1)
    return _affine(_jadd(ja, jb))


def decompress(pub: bytes):
    if len(pub) != 33 or pub[0] not in (2, 3):
        raise ValueError("압축 공개 키(33바이트 02/03)가 아니에요")
    x = int.from_bytes(pub[1:], "big")
    if x >= P:
        raise ValueError("공개 키 x 가 범위 밖이에요")
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y * y % P != y2:
        raise ValueError("곡선 위의 점이 아니에요")
    if (y & 1) != (pub[0] & 1):
        y = P - y
    return (x, y)


def compress(pt) -> bytes:
    return bytes([2 + (pt[1] & 1)]) + pt[0].to_bytes(32, "big")


def _tagged(tag: str, msg: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def taproot_output_key(pub33: bytes) -> bytes:
    pt = decompress(pub33)
    if pt[1] & 1:
        pt = (pt[0], P - pt[1])
    xb = pt[0].to_bytes(32, "big")
    t = int.from_bytes(_tagged("TapTweak", xb), "big")
    if t >= N:
        raise ValueError("taproot tweak 이 범위 밖이에요")
    q = point_add(pt, point_mul_g(t))
    if q is None:
        raise ValueError("taproot 출력 키가 무한원점이에요")
    return q[0].to_bytes(32, "big")


class XPub:
    __slots__ = ("pub", "chain", "depth", "parent_fp", "child", "version")

    def __init__(self, pub: bytes, chain: bytes, depth: int = 0, parent_fp: bytes = b"\x00" * 4, child: int = 0,
                 version: bytes = bytes.fromhex("0488b21e")):
        self.pub, self.chain, self.depth, self.parent_fp, self.child, self.version = pub, chain, depth, parent_fp, child, version

    @classmethod
    def parse(cls, text: str, network: str = "mainnet") -> "XPub":
        info = ac.btc_xpub(text, network)
        body = ac.b58check_decode(info["xpub"])
        node = cls(body[45:78], body[13:45], body[4], body[5:9], int.from_bytes(body[9:13], "big"), body[:4])
        decompress(node.pub)
        return node

    def fingerprint(self) -> bytes:
        return hash160(self.pub)[:4]

    def child_pub(self, i: int) -> "XPub":
        if not 0 <= int(i) < 0x80000000:
            raise ValueError("공개 확장 키로는 강화 경로를 파생할 수 없어요")
        mac = hmac.new(self.chain, self.pub + struct.pack(">I", int(i)), hashlib.sha512).digest()
        il = int.from_bytes(mac[:32], "big")
        if il >= N:
            raise ValueError(f"BIP32 자식 {i} 이 무효(IL ≥ n)")
        pt = point_add(point_mul_g(il), decompress(self.pub))
        if pt is None:
            raise ValueError(f"BIP32 자식 {i} 이 무효(무한원점)")
        return XPub(compress(pt), mac[32:], self.depth + 1, self.fingerprint(), int(i), self.version)

    def serialize(self, version: bytes = None) -> str:
        v = version or self.version
        return ac.b58check_encode(v + bytes([self.depth]) + self.parent_fp + struct.pack(">I", self.child) + self.chain + self.pub)


_HRP = {"mainnet": "bc", "testnet": "tb"}
_B58VER = {"mainnet": (0x00, 0x05), "testnet": (0x6F, 0xC4)}


def bech32_encode(hrp: str, witver: int, prog: bytes) -> str:
    const = 1 if witver == 0 else 0x2BC830A3
    data = [witver] + ac._convertbits(list(prog), 8, 5, True)
    pm = ac._bech32_polymod(ac._hrp_expand(hrp) + data + [0] * 6) ^ const
    chk = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(ac._BECH32_CS[d] for d in data + chk)


SCRIPT_TYPES = ("p2pkh", "p2sh-p2wpkh", "p2wpkh", "p2tr")


def script_and_address(pub33: bytes, script_type: str, network: str = "mainnet"):
    if script_type == "p2wpkh":
        h = hash160(pub33)
        spk, addr = b"\x00\x14" + h, bech32_encode(_HRP[network], 0, h)
    elif script_type == "p2sh-p2wpkh":
        redeem = b"\x00\x14" + hash160(pub33)
        h = hash160(redeem)
        spk, addr = b"\xa9\x14" + h + b"\x87", ac.b58check_encode(bytes([_B58VER[network][1]]) + h)
    elif script_type == "p2pkh":
        h = hash160(pub33)
        spk, addr = b"\x76\xa9\x14" + h + b"\x88\xac", ac.b58check_encode(bytes([_B58VER[network][0]]) + h)
    elif script_type == "p2tr":
        q = taproot_output_key(pub33)
        spk, addr = b"\x51\x20" + q, bech32_encode(_HRP[network], 1, q)
    else:
        raise ValueError(f"모르는 스크립트 종류: {script_type!r}")
    return spk.hex(), addr


class Plan:

    def __init__(self, script_type: str, root: XPub, steps: list, branches: list, network: str = "mainnet"):
        self.script_type, self.root, self.steps, self.branches, self.network = script_type, root, steps, branches, network
        self._nodes = {}
        self._cache = {}

    def _branch_node(self, b: int) -> XPub:
        if b not in self._nodes:
            node = self.root
            for st in self.steps:
                node = node.child_pub(b if st == "*b" else st)
            self._nodes[b] = node
        return self._nodes[b]

    def derive(self, branch: int, index: int):
        k = (int(branch), int(index))
        if k not in self._cache:
            if int(branch) not in self.branches:
                raise ValueError("이 디스크립터에 없는 갈래예요")
            self._cache[k] = script_and_address(self._branch_node(int(branch)).child_pub(int(index)).pub, self.script_type, self.network)
        return self._cache[k]


_TYPE_OF = {"p2pkh": "p2pkh", "p2sh-p2wpkh": "p2sh-p2wpkh", "p2wpkh": "p2wpkh", "p2tr": "p2tr"}


def plan_from_descriptor(text: str, network: str = "mainnet") -> Plan:
    d = ac.btc_descriptor(text, network)
    body = d["descriptor"].rsplit("#", 1)[0]
    m = re.search(r"([1-9A-HJ-NP-Za-km-z]{100,120})((?:/(?:\d+|<\d+;\d+>))*)/\*", body)
    if not m:
        raise ValueError("디스크립터 키 경로를 읽지 못했어요")
    steps = []
    for s in re.findall(r"/(\d+|<\d+;\d+>)", m.group(2)):
        if s.startswith("<"):
            steps.append("*b")
        else:
            v = int(s)
            if v >= 0x80000000:
                raise ValueError("공개 확장 키로는 강화 경로를 파생할 수 없어요")
            steps.append(v)
    if "*b" not in steps:
        if not steps:
            raise ValueError("받는(0)·잔돈(1) 갈래가 없어요")
        steps[-1] = "*b"
    return Plan(_TYPE_OF[d["script_type"]], XPub.parse(d["xpub"], network), steps, list(d["branches"]), network)


def descriptor_from_xpub(xpub_text: str, script_type: str = None, network: str = "mainnet", origin: str = None) -> str:
    info = ac.btc_xpub(xpub_text, network)
    hint = info["script_hint"]
    st = script_type or hint
    if st not in ("pkh", "sh(wpkh)", "wpkh", "tr"):
        raise ValueError("이 확장 키는 주소 형식을 알 수 없어요 — pkh · sh(wpkh) · wpkh · tr 중 하나를 고르세요")
    if hint and script_type and script_type != hint:
        raise ValueError(f"{info['kind']} 는 {hint} 형식 키예요 — 다른 형식으로 바꿔 쓰지 않아요")
    node = XPub.parse(info["xpub"], network)
    std = node.serialize(bytes.fromhex("0488b21e" if network == "mainnet" else "043587cf"))
    key = (f"[{origin}]" if origin else "") + std + "/<0;1>/*"
    body = {"pkh": f"pkh({key})", "sh(wpkh)": f"sh(wpkh({key}))", "wpkh": f"wpkh({key})", "tr": f"tr({key})"}[st]
    return body + "#" + ac.desc_checksum(body)
