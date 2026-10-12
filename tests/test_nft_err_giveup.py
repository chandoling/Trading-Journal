#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import os

import nft

chk = H.chk
CLOCK = [1791000000.0]
DAY = 86400
CFG = {"wallets": [], "chains": {}, "nft": {"enabled": True}}


class Router:
    def __init__(self):
        self.routes, self.calls = {}, []

    def on(self, frag, resp):
        self.routes[frag] = resp

    def __call__(self, url, data=None, headers=None):
        self.calls.append(url)
        hit = [f for f in self.routes if f in url]
        if not hit:
            return 404, None
        r = self.routes[max(hit, key=len)]
        return r(url) if callable(r) else r

    def n(self, frag):
        return sum(1 for u in self.calls if frag in u)


def mk(r, d, env=None):
    os.makedirs(os.path.join(H.TMP, d), exist_ok=True)
    env = {"TJ_OPENSEA_KEY": "OSKEY-A"} if env is None else env
    kw = {k + "_path": os.path.join(H.TMP, d, k + ".json") for k in ("hold", "fp", "prefs")}
    return nft.Tracker(cfg_fn=lambda: CFG, px_fn=lambda s: 2700.0 if s == "ETH" else (40.0 if s == "HYPE" else None),
                       rate_fn=lambda: 1400.0, http=r, sleep=lambda s: None, now=lambda: CLOCK[0], env_fn=lambda k: env.get(k, ""),
                       gate_fn=lambda: {}, budget_path=os.path.join(H.TMP, d, "budget.json"), **kw)


W = "0x" + "11" * 20
BERA = "0x" + "be" * 20
RAR = "0x" + "ab" * 20
HYP = "0x" + "9f" * 20
OLD = "0x" + "d4" * 20
REC = "0x" + "e5" * 20


def add(T, ch, ca, nm):
    key = f"{ch}:{ca}"
    T.hold["cols"][key] = {"chain": ch, "ca": ca, "name": nm, "sym": "", "std": "ERC-721", "seen": CLOCK[0], "first": CLOCK[0]}
    T.hold["pairs"].setdefault(f"{ch}:{W}", {"items": {}, "at": CLOCK[0], "err": None})["items"][key] = {"n": 1, "ids": ["1"]}
    T.hold["acq"][key] = {"kind": "bought", "at": CLOCK[0], "tries": 1}
    return key


def run(T, secs):
    t_end = CLOCK[0] + secs
    while CLOCK[0] < t_end:
        T.refresh_fp()
        CLOCK[0] += T._loop_wait()


def row_of(v, key):
    for sec in ("tracked", "candidates", "hidden", "watch"):
        for r9 in v.get(sec) or []:
            if r9.get("key") == key:
                return r9
    return None


HYP_OK = (200, {"contract_address": HYP, "floor_price": {"native_currency": 1200.0, "usd": 48000}, "native_currency_symbol": "HYPE",
                "volume_24h": {"native_currency": 5000.0}, "one_day_sales": 4, "id": "hypurr", "name": "Hypurr"})
r = Router()
r.on(f"api.opensea.io/api/v2/chain/berachain/contract/{BERA}", (500, None))
r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{RAR}", (200, {"address": "0x" + "00" * 20, "collection": "rarible"}))
r.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{OLD}", (500, None))
r.on(f"/nfts/hyperevm/contract/{HYP}", HYP_OK)
T = mk(r, "a")
kb, kr, kh, ko = add(T, "berachain", BERA, "Bera NFT Lottery"), add(T, "eth", RAR, "Rarible"), add(T, "hyperevm", HYP, "Hypurr"), add(T, "eth", OLD, "Old")
T.fp["fp"][ko] = {"src": "os", "native": 0.5, "sym": "ETH", "at": CLOCK[0] - 600}
T.fp["chk"][ko] = CLOCK[0] - 600
t0 = CLOCK[0]
run(T, DAY)
nb_cg, nb_os = r.n(f"nfts/berachain/contract/{BERA}"), r.n(f"chain/berachain/contract/{BERA}")
nr_cg, nr_os = r.n(f"nfts/ethereum/contract/{RAR}"), r.n(f"chain/ethereum/contract/{RAR}")
chk(nb_cg <= 3 and nb_os <= 3 and (T.fp.get("neg") or {}).get(kb, {}).get("src") == "cg",
    "R1 오픈시 500 지속 + 코인게코 404 = 3번 뒤 '시세 없음' 7일(24시간 CG ≤ 3 · OS ≤ 3)", (nb_cg, nb_os, (T.fp.get("neg") or {}).get(kb)))
chk(nr_cg <= 3 and nr_os <= 3 and kr in (T.fp.get("neg") or {}), "R2 오픈시 주소 불일치 + 코인게코 404 = 같음", (nr_cg, nr_os))
nh = r.n(f"nfts/hyperevm/contract/{HYP}")
chk(1 <= nh <= 7, "R3 코인게코 전용 체인 추적 = 4시간마다(24시간 CG ≤ 7)", nh)
fh = (T.fp.get("fp") or {}).get(kh) or {}
CLOCK[0] = float(fh.get("at") or 0) + 4.5 * 3600
rh = row_of(T.view(CFG), kh) or {}
chk(rh.get("fp") and not rh["fp"].get("stale"), "R3 4시간 반 지난 코인게코 전용 체인 값 = '오래됨' 아님(주기 4시간)", rh.get("fp"))
CLOCK[0] = float(fh.get("at") or 0) + 6 * 3600
rh = row_of(T.view(CFG), kh) or {}
chk(rh.get("fp") and rh["fp"].get("stale"), "R3 6시간 지난 값 = '오래됨'", rh.get("fp"))
fo = (T.fp.get("fp") or {}).get(ko) or {}
chk(fo.get("native") == 0.5 and fo.get("err") and ko not in (T.fp.get("neg") or {}),
    "R4 직전 시세 있음 = 오픈시 오류가 이어져도 부정 캐시 안 함(직전 값 · 오류 표시)", (fo, (T.fp.get("neg") or {}).get(ko)))

CLOCK[0] = t0 + 3 * DAY
r5 = Router()
r5.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{REC}", (500, None))
T5 = mk(r5, "r5")
k5 = add(T5, "eth", REC, "Recover")
T5.fp["oskey"] = {"fp": nft._kfp("OSKEY-A"), "at": CLOCK[0]}
for _ in range(2):
    T5.fetch_fp(k5, T5.hold["cols"][k5])
    CLOCK[0] += 1801
r5.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{REC}", (200, {"address": REC, "collection": "rec-x"}))
r5.on("api.opensea.io/api/v2/collections/rec-x/stats", (200, {"total": {"floor_price": 0, "floor_price_symbol": "ETH"}}))
oe5 = dict(T5.fp.get("oserr") or {})
rec5 = T5.fetch_fp(k5, T5.hold["cols"][k5])
chk(oe5.get(k5) == 2 and rec5 in ("ok", "none") and k5 not in (T5.fp.get("oserr") or {}), "R5 오픈시 응답(200) = 오류 횟수 지움", (oe5, rec5, T5.fp.get("oserr")))
CLOCK[0] += 1801
T5.fp.get("map", {}).pop(k5, None)
T5.fp.get("neg", {}).pop(k5, None)
r5.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{REC}", (500, None))
outs = []
for _ in range(2):
    outs.append(T5.fetch_fp(k5, T5.hold["cols"][k5]))
    CLOCK[0] += 1801
chk(outs == ["err", "err"] and k5 not in (T5.fp.get("neg") or {}), "R5 오픈시 회복 뒤 오류 2번 = 포기 안 함(횟수 처음부터)", (outs, (T5.fp.get("neg") or {}).get(k5)))

env6 = {"TJ_OPENSEA_KEY": "OSKEY-A"}
CLOCK[0] = t0 + 5 * DAY
r6 = Router()
r6.on(f"api.opensea.io/api/v2/chain/ethereum/contract/{RAR}", (500, None))
T6 = mk(r6, "r6", env=env6)
k6 = add(T6, "eth", RAR, "Rarible")
T6._os_sync_key()
for _ in range(3):
    T6.fetch_fp(k6, T6.hold["cols"][k6])
    CLOCK[0] += 1801
neg6 = k6 in (T6.fp.get("neg") or {})
env6["TJ_OPENSEA_KEY"] = "OSKEY-B"
T6._os_sync_key()
chk(neg6 and k6 not in (T6.fp.get("neg") or {}) and k6 in {k for k, _c in T6.due_fp()}, "R6 키 바뀜 = 포기 부정 캐시 풀림 · 다시 물을 대상", neg6)

CLOCK[0] = t0 + 7 * DAY
T7 = mk(Router(), "r7")
k7 = "eth:0x" + "c9" * 20
T7.hold["cols"][k7] = {"chain": "eth", "ca": k7.split(":")[1], "name": "CG coll", "rep": "ok"}
T7.fp["fp"][k7] = {"src": "cg", "native": 1.0, "sym": "ETH", "vol24": 5.0, "at": CLOCK[0]}
T7.fp["chk"][k7] = CLOCK[0]
CLOCK[0] += 3601
chk(k7 in {k for k, _c in T7.due_fp()}, "R7 eth 코인게코 출처 추적 = 1시간 뒤 다시(종전)")

H.finish()
