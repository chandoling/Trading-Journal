import hashlib
import json
import time

import address_codec as ac
import bf_engine

BASE_T = int(time.time()) - 20 * 86400


def _h(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


class FakeChain:
    def __init__(self, height=100, page=25, hosts=("https://blockstream.example/api", "https://mempool.example/api")):
        self.blocks = []
        self.txs = {}
        self.where = {}
        self.mempool = []
        self.page = page
        self.fails = []
        self.calls = []
        self.hide_prevout = set()
        self.down = set()
        self.hosts = hosts
        self.seq = 0
        for h in range(0, height + 1):
            self.blocks.append((h, _h("blk", h, 0), BASE_T + h * 600, []))

    @property
    def height(self):
        return self.blocks[-1][0]

    def _new_txid(self):
        self.seq += 1
        return _h("tx", self.seq)

    def fund(self, addr, value, n_out=1):
        txid = self._new_txid()
        self.txs[txid] = {"vin": [{"coinbase": True}], "vout": [(addr, value)] * n_out}
        self.mempool.append(txid)
        return txid

    def spend(self, ins, outs, fee=None):
        txid = self._new_txid()
        tot = sum(self.txs[t]["vout"][n][1] for t, n in ins)
        if fee is not None:
            assert tot - sum(v for _a, v in outs) == fee, (tot, outs, fee)
        self.txs[txid] = {"vin": [{"txid": t, "vout": n} for t, n in ins], "vout": list(outs)}
        self.mempool.append(txid)
        return txid

    def mine(self, txids=None, salt=0, t=None):
        txids = list(self.mempool if txids is None else txids)
        h = self.height + 1
        self.blocks.append((h, _h("blk", h, salt), int(t) if t is not None else max(b[2] for b in self.blocks) + 600, txids))
        for t in txids:
            if t in self.mempool:
                self.mempool.remove(t)
            self.where[t] = h
        return h

    def mine_empty(self, n=1, salt=0):
        for _ in range(n):
            self.mine([], salt=salt)

    def reorg(self, depth, keep=None, salt=1):
        old = self.blocks[-depth:]
        del self.blocks[-depth:]
        for _h9, _hs, _t, txs in old:
            for t in txs:
                self.where.pop(t, None)
        keep = list(keep or [])
        for i in range(depth):
            put = keep if i == 0 else []
            self.mine(put, salt=salt)

    def conf(self, txid):
        return self.height - self.where[txid] + 1 if txid in self.where else 0

    def fail_next(self, n=1, kind="http429", match=""):
        self.fails.append([match, kind, n])

    def _blk(self, h):
        for b in self.blocks:
            if b[0] == h:
                return b
        return None

    def _txjson(self, txid, with_prevout=True):
        raw = self.txs[txid]
        vin = []
        tot_in = 0
        cb = False
        for v in raw["vin"]:
            if v.get("coinbase"):
                cb = True
                vin.append({"txid": "0" * 64, "vout": 4294967295, "is_coinbase": True, "prevout": None})
                continue
            a, val = self.txs[v["txid"]]["vout"][v["vout"]]
            tot_in += val
            po = {"scriptpubkey": ac.btc_address(a)["script"], "scriptpubkey_address": a, "value": val}
            vin.append({"txid": v["txid"], "vout": v["vout"], "is_coinbase": False,
                        "prevout": po if (with_prevout and txid not in self.hide_prevout) else None})
        vout = [{"scriptpubkey": ac.btc_address(a)["script"], "scriptpubkey_address": a, "value": val} for a, val in raw["vout"]]
        fee = 0 if cb else tot_in - sum(o["value"] for o in vout)
        h = self.where.get(txid)
        if h is not None:
            b = self._blk(h)
            st = {"confirmed": True, "block_height": h, "block_hash": b[1], "block_time": b[2]}
        else:
            st = {"confirmed": False}
        return {"txid": txid, "version": 2, "locktime": 0, "vin": vin, "vout": vout, "fee": fee, "status": st, "size": 200, "weight": 800}

    def _touches(self, txid, addr):
        raw = self.txs[txid]
        if any(a == addr for a, _v in raw["vout"]):
            return True
        return any(not v.get("coinbase") and self.txs[v["txid"]]["vout"][v["vout"]][0] == addr for v in raw["vin"])

    def _hist(self, addr):
        rows = []
        for h, _hs, _t, txs in self.blocks:
            for k, t in enumerate(txs):
                if self._touches(t, addr):
                    rows.append((h, k, t))
        rows.sort(reverse=True)
        return [t for _h9, _k, t in rows]

    def _stats(self, addr):
        f = s = n = 0
        for t in self._hist(addr):
            n += 1
            raw = self.txs[t]
            f += sum(v for a, v in raw["vout"] if a == addr)
            s += sum(self.txs[v["txid"]]["vout"][v["vout"]][1] for v in raw["vin"]
                     if not v.get("coinbase") and self.txs[v["txid"]]["vout"][v["vout"]][0] == addr)
        mem = sum(1 for t in self.mempool if self._touches(t, addr))
        return {"address": addr, "chain_stats": {"funded_txo_count": 0, "funded_txo_sum": f, "spent_txo_count": 0, "spent_txo_sum": s,
                                                 "tx_count": n},
                "mempool_stats": {"funded_txo_count": 0, "funded_txo_sum": 0, "spent_txo_count": 0, "spent_txo_sum": 0, "tx_count": mem}}

    def transport(self, url):
        host = url.split("/")[2]
        path = "/" + url.split("/", 3)[3][len("api"):].lstrip("/") if "/api" in url else url
        path = "/" + path.lstrip("/")
        self.calls.append((host, path))
        if host in self.down:
            raise bf_engine.NetError(f"conn: {host}", "conn", host=host)
        for f in self.fails:
            if f[2] > 0 and f[0] in path:
                f[2] -= 1
                kind = f[1]
                if kind == "null":
                    return None
                if kind == "short":
                    return [] if "/txs/chain" in path else {"chain_stats": {}}
                raise bf_engine.NetError(f"{kind}: {host} 합성 오류", kind, code=429 if kind == "http429" else None, host=host)
        parts = [p for p in path.split("/") if p]
        if parts == ["blocks"] or (parts[0] == "blocks" and len(parts) == 2):
            top = self.height if len(parts) == 1 else int(parts[1])
            return [{"id": b[1], "height": b[0], "timestamp": b[2], "tx_count": len(b[3])} for b in reversed(self.blocks) if b[0] <= top][:10]
        if parts[0] == "tx" and len(parts) == 2:
            if parts[1] not in self.txs:
                raise bf_engine.NetError("http4xx: 404", "http4xx", code=404, host=host)
            return json.loads(json.dumps(self._txjson(parts[1])))
        if parts[0] == "address":
            addr = parts[1]
            if len(parts) == 2:
                return self._stats(addr)
            if parts[2:4] == ["txs", "chain"]:
                hist = self._hist(addr)
                if len(parts) == 5:
                    if parts[4] not in hist:
                        raise bf_engine.NetError("http4xx: 400", "http4xx", code=400, host=host)
                    hist = hist[hist.index(parts[4]) + 1:]
                return [self._txjson(t) for t in hist[:self.page]]
        raise bf_engine.NetError(f"http4xx: 404 {path}", "http4xx", code=404, host=host)


def cfg_nonevm(hosts=("https://blockstream.example/api", "https://mempool.example/api"), **kw):
    d = {"esplora": list(hosts), "min_conf": 3, "rps": 50, "calls_per_page": 40}
    d.update(kw)
    return {"btc": d}
