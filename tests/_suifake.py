import json
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _harness as T

MAINNET_ID = "4btiuiMPvEENsttpZC7CZ53DruC3MAgfznDbASZ7DR6S"
SUI_T = "0x" + "0" * 63 + "2::sui::SUI"
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def digest(i):
    s, n = "", 10 ** 30 + i * 7919
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return ("Dg" + s + "x" * 44)[:44]


class Chain:
    def __init__(self, tip=20_000_000, now=None):
        self.now = int(now or time.time())
        self.tip = tip
        self.base = self.now - tip
        self.txs = []
        self.bal = {}
        self.meta = {}
        self.chain_id = MAINNET_ID
        self.avail = (0, self.base)
        self.page_cap = 50
        self.bc_cap = 50
        self.bal_cap = 50
        self.bal_min_ck = 0
        self.inject = {}
        self.calls = []
        self.lock = threading.Lock()
        self._seq = 0

    def ts(self, ck):
        return self.base + ck

    def iso(self, ck):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.ts(ck))) + ".250Z"

    def add(self, ck, changes, sender=None, sponsor=None, gas=(1000, 2000, 500), status="SUCCESS", d=None):
        self._seq += 1
        t = {"digest": d or digest(self._seq), "ck": ck, "seq": self._seq, "sender": sender, "sponsor": sponsor or sender,
             "status": status, "gas": gas, "changes": list(changes)}
        self.txs.append(t)
        self.txs.sort(key=lambda x: (x["ck"], x["seq"]))
        return t["digest"]

    @staticmethod
    def fee(t):
        c, s, r = t["gas"]
        return c + s - r

    def affected(self, t, a):
        return a in (t["sender"], t["sponsor"]) or any(o == a for o, _ty, _v in t["changes"])

    def bc_page(self, t, after):
        i = int(after) + 1 if after is not None else 0
        part = t["changes"][i:i + self.bc_cap]
        nodes = [{"owner": ({"address": o} if o else None), "coinType": {"repr": ty}, "amount": str(v)} for o, ty, v in part]
        end = i + len(part) - 1
        return {"pageInfo": {"hasNextPage": end + 1 < len(t["changes"]), "endCursor": str(end) if part else None}, "nodes": nodes}

    def node(self, t):
        c, s, r = t["gas"]
        return {"digest": t["digest"], "sender": {"address": t["sender"]} if t["sender"] else None,
                "gasInput": {"gasSponsor": {"address": t["sponsor"]} if t["sponsor"] else None},
                "effects": {"status": t["status"], "timestamp": self.iso(t["ck"]), "checkpoint": {"sequenceNumber": t["ck"]},
                            "gasEffects": {"gasSummary": {"computationCost": c, "storageCost": s, "storageRebate": r}},
                            "balanceChanges": self.bc_page(t, None)}}

    def answer(self, op, v):
        if op == "SuiPreflight":
            return {"chainIdentifier": self.chain_id, "checkpoint": {"sequenceNumber": self.tip, "timestamp": self.iso(self.tip)},
                    "serviceConfig": {"maxPageSize": self.page_cap,
                                      "r": {"first": {"sequenceNumber": self.avail[0], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.avail[1]))},
                                            "last": {"sequenceNumber": self.tip, "timestamp": self.iso(self.tip)}}}}
        if op in ("SuiTxFwd", "SuiTxBack"):
            a, n = v["a"], min(int(v["n"]), self.page_cap)
            rows = [t for t in self.txs if t["ck"] <= self.tip and self.affected(t, a)]
            if op == "SuiTxFwd":
                if v.get("ack") is not None:
                    rows = [t for t in rows if t["ck"] > int(v["ack"])]
                if v.get("after"):
                    pos = tuple(map(int, v["after"].split(":")[1:]))
                    rows = [t for t in rows if (t["ck"], t["seq"]) > pos]
                part = rows[:n]
                pi = {"hasNextPage": len(rows) > n, "endCursor": f"p:{part[-1]['ck']}:{part[-1]['seq']}" if part else None}
            else:
                if v.get("bck") is not None:
                    rows = [t for t in rows if t["ck"] < int(v["bck"])]
                if v.get("before"):
                    pos = tuple(map(int, v["before"].split(":")[1:]))
                    rows = [t for t in rows if (t["ck"], t["seq"]) < pos]
                part = rows[-n:] if n else []
                pi = {"hasPreviousPage": len(rows) > n, "startCursor": f"p:{part[0]['ck']}:{part[0]['seq']}" if part else None}
            return {"checkpoint": {"sequenceNumber": self.tip}, "transactions": {"pageInfo": pi, "nodes": [self.node(t) for t in part]}}
        if op == "SuiTx":
            t = next((t for t in self.txs if t["digest"] == v["d"] and t["ck"] <= self.tip), None)
            return {"transaction": self.node(t) if t else None}
        if op == "SuiTxBc":
            t = next((t for t in self.txs if t["digest"] == v["d"]), None)
            return {"transaction": {"digest": t["digest"], "effects": {"balanceChanges": self.bc_page(t, v.get("after"))}} if t else None}
        if op == "SuiCk":
            return {"checkpoint": {"sequenceNumber": self.tip, "timestamp": self.iso(self.tip)}}
        if op == "SuiCkAt":
            return {"checkpoint": {"sequenceNumber": int(v["c"]), "timestamp": self.iso(int(v["c"]))}}
        if op == "SuiBal":
            if int(v["c"]) < self.bal_min_ck:
                raise _GqlErr("Request is outside consistent range")
            rows = self.bal.get(v["a"], [])
            i = int(v["after"]) + 1 if v.get("after") else 0
            part = rows[i:i + self.bal_cap]
            end = i + len(part) - 1
            nodes = [{"coinType": {"repr": ty}, "totalBalance": str(tot), "coinBalance": None if cb is None else str(cb),
                      "addressBalance": None if ab is None else str(ab)} for ty, tot, cb, ab in part]
            return {"address": {"balances": {"pageInfo": {"hasNextPage": end + 1 < len(rows), "endCursor": str(end) if part else None},
                                              "nodes": nodes}}}
        if op == "SuiMeta":
            out = {}
            for k, ty in v.items():
                m = self.meta.get(ty)
                out["m" + k[1:]] = {"decimals": m[1], "symbol": m[0]} if m else None
            return out
        raise _GqlErr(f"Unknown operation {op}")


class _GqlErr(Exception):
    pass


def mk_handler(ch):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, extra=None, clen=None):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(clen if clen is not None else len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            op, v = req.get("operationName"), req.get("variables") or {}
            with ch.lock:
                ch.calls.append((op, dict(v)))
                q = ch.inject.get(op) or []
                kind = q.pop(0) if q else None
            if kind == "http429":
                return self._send(429, b'{"errors":[{"message":"rate limited"}]}', {"Retry-After": "0"})
            if kind == "http500":
                return self._send(500, b"oops")
            if kind == "badjson":
                return self._send(200, b'{"data": {"transactions": ')
            if kind == "short":
                body = b'{"data": {"checkpoint": {"sequenceNumber": 1}}}'
                return self._send(200, body[:20], clen=len(body))
            if kind == "gqlerr":
                return self._send(200, json.dumps({"data": None, "errors": [{"message": "internal error"}]}).encode())
            if kind == "range":
                return self._send(200, json.dumps({"data": None, "errors": [{"message": "Request is outside consistent range"}]}).encode())
            try:
                data = ch.answer(op, v)
            except _GqlErr as e:
                return self._send(200, json.dumps({"data": None, "errors": [{"message": str(e)}]}).encode())
            if kind == "partial":
                return self._send(200, json.dumps({"data": data, "errors": [{"message": "partial failure"}]}).encode())
            if kind == "nulltx" and "transaction" in data:
                data = {"transaction": None}
            if kind == "noeffects" and isinstance(data.get("transaction"), dict):
                data["transaction"]["effects"] = None
            if kind == "notime" and isinstance(data.get("transaction"), dict):
                data["transaction"]["effects"]["timestamp"] = None
            if kind == "nogas" and isinstance(data.get("transaction"), dict):
                data["transaction"]["effects"]["gasEffects"] = None
            if kind == "nullowner" and isinstance(data.get("transaction"), dict):
                data["transaction"]["effects"]["balanceChanges"]["nodes"][0]["owner"] = None
            if kind == "nopayer" and isinstance(data.get("transaction"), dict):
                data["transaction"]["sender"] = None
                data["transaction"]["gasInput"] = None
            if kind == "nogasinput" and isinstance(data.get("transaction"), dict):
                data["transaction"]["gasInput"] = None
            if kind == "nosponsorkey" and isinstance(data.get("transaction"), dict):
                data["transaction"]["gasInput"] = {}
            if kind == "badsponsor" and isinstance(data.get("transaction"), dict):
                data["transaction"]["gasInput"] = {"gasSponsor": {"address": "0xzz"}}
            if kind == "nullsponsor" and isinstance(data.get("transaction"), dict):
                data["transaction"]["gasInput"] = {"gasSponsor": None}
            if kind == "testnet" and "chainIdentifier" in data:
                data["chainIdentifier"] = "69WiPg3DAQiwdxfncX6wYQ2siKwAe6L9BZthQea3JNMD"
            self._send(200, json.dumps({"data": data}).encode())
    return H


_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _loop_urlopen(url, data=None, timeout=30, *a, **k):
    u = getattr(url, "full_url", url)
    if urllib.parse.urlsplit(str(u)).hostname not in ("127.0.0.1", "localhost"):
        return T._guard_urlopen(url, data, timeout, *a, **k)
    return _OP.open(url, data=data, timeout=timeout)


_loop_urlopen._tj_test_mock = True


def start(ch):
    import bf_engine
    bf_engine.urllib.request.urlopen = _loop_urlopen
    bf_engine._POLICY_OVERRIDES["127.0.0.1"] = {"rate": 10000.0, "burst": 10000, "conc": 16, "breaker_fails": 100, "open_wait": 0}
    with bf_engine._GATES_LOCK:
        bf_engine._GATES.pop("127.0.0.1", None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mk_handler(ch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/graphql"
