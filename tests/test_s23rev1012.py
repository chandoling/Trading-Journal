#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 2 and sys.argv[1] == "--case":
    import _harness as T
    import time
    from datetime import datetime, timezone
    from decimal import Decimal

    os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
    os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
    json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
    json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
    W = "0x" + "1a" * 20
    json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "rpcs": ["https://rpc.invalid"]}},
               "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"}], "backfill_months": 2},
              open(os.path.join(T.TMP, "config.json"), "w"))
    import common
    import core
    import db as dbm
    import ex_foreign as X
    import histcurve
    import netpace
    import web

    NOW = int(time.time())
    core.dm = lambda *a, **k: None
    for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker"):
        if hasattr(web.StateBuilder, _m):
            setattr(web.StateBuilder, _m, lambda self: None)
    netpace.wait = lambda *a, **k: None
    C = core.Core(common.load_config())
    C._quote_usd = lambda quote, ts: Decimal("0.001") if quote == "KRW" else Decimal(1)
    C.px.fx_at = lambda *a, **k: 1000.0
    json.dump({"usd": {"USDT": 1.0, "USDC": 1.0}, "usd_ts": {"USDT": NOW, "USDC": NOW}, "rate": 1000.0, "updated": NOW, "fx_basis": 1000.0,
               "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {}, "ex_usd": {"bithumb:USDT": 1.0}, "ex_ts": {"bithumb:USDT": NOW}},
              open(web.SPOT_PATH, "w"))
    web.pricing.PxCache.candle_usd = lambda self, sym, ms: None
    web.pricing.PxCache.fx_at = lambda self, ms: 1000.0
    web.pricing._gj = lambda *a, **k: None
    histcurve.DAYCLOSE.lookup = lambda spec, iso, now=None, w=0.0, ask=True, old=False: (None, "pending")
    histcurve.DAYCLOSE.lookup._tj_test_mock = True
    common.atomic_write_json(web.PREFS_PATH, {"plans": {}, "ignored": []})

    def post(ex, t, sym, qty, uid="seed"):
        aid = C._exf_asset(ex, sym)
        dec = C.conn.execute("SELECT decimals FROM assets WHERE asset_id=?", (aid,)).fetchone()[0]
        qb = int(Decimal(str(qty)) * Decimal(10) ** int(dec))
        C.conn.execute("INSERT INTO postings(source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, leg_kind, event, classifier_ver)"
                       " VALUES('exchange', ?, ?, 0, ?, ?, ?, ?, 'move_in', 'EXF_DEPOSIT', ?)", (f"{ex}:deposit", uid, t, aid, f"exchange:{ex}", str(qb), core.CLASSIFIER_VER))
        C._bump_position(aid, qb, f"exchange:{ex}")

    def build():
        for p in (web.DAILY_PATH, web.DAILY_PX_PATH):
            if os.path.exists(p):
                os.remove(p)
        b = web.StateBuilder()
        b.skip_gen_check = True
        conn = dbm.open_db(common.DB_PATH, readonly=True)
        try:
            return b._build(conn)["fields"], b
        finally:
            conn.close()

    def snap(ex, ts, balances):
        common.atomic_write_json(os.path.join(common.STATE_DIR, f"exf_balances_{ex}.json.view"), {"ts": ts, "balances": balances})

    def iso(ts):
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()

    def usd_total(f):
        return sum(float(r.get("qty") or 0) * float(r.get("price") or 0) for r in (f.get("coins") or []) + (f.get("stables") or []))

    case = sys.argv[2]
    out = {}
    if case.startswith("krw_"):
        _k, side, where, var = (case.split("_") + ["plain"])[:4]
        ts = NOW - 900
        if var == "three":
            legs = [(ts - 120, 10000), (ts + 120, 10000), (ts + 240, 30000)]
            pre = 10000
        else:
            t1, t2 = {"cross": (ts - 120, ts + 120), "before": (ts - 300, ts - 120), "after": (ts + 120, ts + 300)}[where]
            legs = [(t1, 20000), (t2, 30000)]
            pre = sum(f for t, f in legs if t < ts)
        fee = 50 if var == "fee" else 0
        cash0 = 100000 if side == "buy" else 0
        if side == "sell":
            post("bithumb", ts - 2000, "USDT", 100)
        C.conn.execute("INSERT INTO meta(k, v) VALUES('recon_done_exf_bithumb', ?)", (str(ts - 3000),))
        fee_pre = (Decimal(fee) * pre / 50000) if fee else 0
        cash_snap = float(cash0 + (-1 if side == "buy" else 1) * pre - fee_pre)
        snap("bithumb", ts, {"KRW": cash_snap})
        trades = [{"created_at": iso(t), "funds": str(f), "volume": str(f // 1000), "price": "1000"} for t, f in legs]
        order = {"uuid": "c-" + case, "market": "KRW-USDT", "side": "bid" if side == "buy" else "ask", "state": "done", "ord_type": "limit",
                 "created_at": iso(ts - 4000), "executed_volume": "50", "executed_funds": "50000" if var != "summis" else "49000",
                 "paid_fee": str(fee), "trades_count": len(trades) + (1 if var == "cntmis" else 0), "trades": trades}

        def call(path, params=None):
            if path == "/v1/orders":
                return []
            if path == "/v1/order":
                return order
            raise AssertionError(path)
        sl9 = X.time.sleep
        X.time.sleep = lambda s: None
        try:
            fills = X._bithumb_track(call, {"open_track": {order["uuid"]: {"c": order["created_at"], "m": "KRW-USDT"}}}, [], {}, NOW)
        finally:
            X.time.sleep = sl9
        C._consume_exf_fills({"exchange": "bithumb", "fills": fills})
        C.conn.commit()
        n_post = C.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
        C._consume_exf_fills({"exchange": "bithumb", "fills": fills})
        C.conn.commit()
        f, b = build()
        krw = sum(float(r.get("krw") or 0) for r in f.get("fiats") or [] if r.get("ex") == "빗썸")
        out = {"krw": krw, "total": round(krw + usd_total(f) * 1000, 2), "legs": fills[0].get("cashlegs"),
               "repost_same": C.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == n_post,
               "tl_split": len(web.StateBuilder()._bithumb_krw_timeline(C.conn) or ()),
               "tl_order": len(web.StateBuilder()._bithumb_krw_timeline(C.conn, split=False) or ())}
    elif case.startswith("tr_"):
        import exprov
        mode = case[3:]
        bs = NOW - 600
        addr = "0x" + "ab" * 20
        post("binance", NOW - 10000, "USDT", 1000)
        C.conn.execute("INSERT INTO meta(k, v) VALUES('recon_done_exf_binance', ?)", (str(NOW - 9000),))
        wd = {"uuid": "wd1", "currency": "USDT", "amount": "1000", "fee": "0", "txid": "0x" + "bc" * 32, "state": "DONE",
              "created_at": iso(NOW - 3600), "done_at": iso(NOW - 3500), "address": addr, "network": "ETH"}
        C._consume_ex({"exchange": "binance", "deposits": [], "withdraws": [wd]})
        d_ts = bs + (20 if mode in ("near", "mixed") else 120)
        dep = {"uuid": "dep-other", "currency": "USDT", "amount": "10", "txid": "0x" + "cd" * 32, "state": "ACCEPTED", "created_at": iso(d_ts), "done_at": iso(d_ts)}
        if mode not in ("zero", "equal"):
            C._consume_ex({"exchange": "okx", "deposits": [dep], "withdraws": []})
        C.conn.commit()
        if mode == "equal":
            post("okx", bs - 1200, "USDT", 1000, uid="old-recv")
            C.conn.commit()
        balances = {"USDT": 0.0 if mode == "zero" else 1000.0}
        if mode == "mixed":
            post("binance", NOW - 10000, "USDC", 500, uid="seed-usdc")
            C._consume_ex({"exchange": "binance", "deposits": [], "withdraws": [dict(wd, uuid="wd2", currency="USDC", amount="500", txid="0x" + "de" * 32)]})
            balances["USDC"] = 500.0
            C.conn.commit()
        snap("okx", bs, balances)
        common.atomic_write_json(web.StateBuilder.OUTFLOW_PATH, {"decisions": {addr: {"verdict": "exchange", "exchange": "okx"}}})
        f, b = build()
        out = {"total": usd_total(f), "expect": {"zero": 0.0, "equal": 1000.0, "mixed": 1510.0}.get(mode, 1010.0)}
    out["net"] = list(T.NET_TRIES)
    print("CASE " + json.dumps(out, default=str), flush=True)
    sys.exit(0)

import _harness as T


def child(case):
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--case", case], cwd=HERE, capture_output=True, text=True, timeout=600)
    for ln in p.stdout.splitlines():
        if ln.startswith("CASE "):
            return json.loads(ln[5:])
    return {"_err": (p.stdout[-600:] + p.stderr[-1200:])}


for side in ("buy", "sell"):
    for where in ("before", "cross", "after"):
        r = child(f"krw_{side}_{where}")
        T.chk(r.get("krw") == 50000.0 and r.get("total") == 100000.0 and r.get("repost_same") and not r.get("net"),
              f"R1 빗썸 {side} 부분 체결 스냅숏 {where} = 원화 5만 · 총 10만 · 재수신 멱등", r)
r = child("krw_sell_cross")
T.chk(r.get("tl_split") == 2 and r.get("tl_order") == 1,
      "R1 (코덱스 s24a) 지금 원화 굴림 = 체결별 2조각 · 지난날 곡선 재료(split=False) = 주문 1건(코인 원장 기장 시각과 같게)", r)
r = child("krw_buy_cross_three")
T.chk(r.get("krw") == 50000.0 and r.get("total") == 100000.0 and len(r.get("legs") or ()) == 3, "R1 체결 3조각(전 1만 · 후 1만·3만) = 원화 5만", r)
for side in ("buy", "sell"):
    r = child(f"krw_{side}_cross_fee")
    T.chk(r.get("legs") and abs(float(r.get("krw") or 0) - 49950.0) < 1e-6, f"R1 {side} 교차 + 원화 수수료 50 = 체결 비례 배분(합 보존) → 원화 49,950", r)
for var in ("cntmis", "summis"):
    r = child(f"krw_buy_cross_{var}")
    T.chk("_err" not in r and not r.get("legs"), f"R1 체결 정보 불완전({var}) = 체결 조각 안 만듦(종전 주문 시각 하나)", r)

for mode in ("near", "far", "zero", "equal", "mixed"):
    r = child(f"tr_{mode}")
    T.chk(r.get("total") == r.get("expect") and not r.get("net"), f"R2 받는 거래소 첫 대사 전 전송 중 ({mode}) = {r.get('expect')}", r)

import common
import core
import db as dbm
import recon
import web
import time
from decimal import Decimal

NOW = int(time.time())
SW, PK = "So1" + "c" * 40, "Stk" + "9" * 40
LOC_W, LOC_S = f"wallet:sol:{SW}", f"wallet:sol:{SW}:stake:{PK}"
PF = os.path.join(common.STATE_DIR, core.Core.PROV_FILE)
SP = os.path.join(common.STATE_DIR, "sol_stake.json")
_real_rpc = recon._rpc
LIVE = {}
CALLS = []


def fake_rpc(u, method, params, **k):
    CALLS.append((u, method))
    if method != "getMultipleAccounts" or LIVE.get("_fail"):
        raise RuntimeError("시험: 조회 실패")
    return {"value": [None if LIVE.get(pk) is None else {"lamports": LIVE[pk]} for pk in params[0]]}


recon._rpc = fake_rpc


def r3(name, *, wallet_now, stake_snap, stake_now, records, expect, fail=False):
    cb = dbm.open_db(os.path.join(T.TMP, f"r3_{abs(hash(name))}.db"))
    cb.execute("INSERT INTO asset_groups (group_id, name, norm_decimals) VALUES (91, 'SOL#r3', 18)")
    cb.execute("INSERT INTO assets (asset_id, kind, chain, address, symbol, decimals, confirmed, hidden, group_id) VALUES (91, 'native', 'sol', NULL, 'SOL', 9, 1, 0, 91)")
    for i, (loc9, q9, t9) in enumerate(records):
        cb.execute("INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base, cost_usd,"
                   " cost_krw, leg_kind, event, classifier_ver) VALUES (?, 'chain_tx', 'sol', ?, 0, ?, 91, ?, ?, NULL, NULL, 'move', 'stake', 5)",
                   (i + 1, f"sig{i}", t9, loc9, str(q9 * 10 ** 9)))
    cb.commit()
    json.dump({"ts": NOW - 900, "accounts": {PK: {"w": SW, "lamports": stake_snap * 10 ** 9}}}, open(SP, "w"))
    LIVE.clear()
    LIVE[PK] = None if stake_now is None else stake_now * 10 ** 9
    if fail:
        LIVE["_fail"] = True
    real_fast = recon.fetch_sol_balances_fast
    recon.fetch_sol_balances_fast = lambda *a, **k: {"per_wallet": {SW: {("native", None): wallet_now * 10 ** 9}}, "_meta": {}}
    try:
        bal = core.Core._prov_sol_fetch(["https://sol.invalid"], [SW], now=NOW, native_url="https://head.invalid")
    finally:
        recon.fetch_sol_balances_fast = real_fast
    pk9 = core.Core._prov_pack(bal, "chain", NOW - 5, req=[SW], t1=NOW, kind="sol")
    pk9["stake_ts"] = int(bal.get("_stake_ts") or 0)
    pk9["stake_live"] = int(bal.get("_stake_live") or 0)
    json.dump({"sol": pk9}, open(PF, "w"))
    its = web.StateBuilder._prov_items(object(), cb)
    led = sum((Decimal(q) for _l, q, _t in records), Decimal(0))
    disp = led + sum((it["qty"] for it in its if it.get("qty") is not None), Decimal(0))
    pre = [tuple(r) for r in cb.execute("SELECT * FROM postings")]
    T.chk(disp == Decimal(expect) and pre == [tuple(r) for r in cb.execute("SELECT * FROM postings")],
          name, {"display": str(disp), "expect": expect, "live": pk9.get("stake_live"), "its": [(it["loc"], str(it["qty"])) for it in its]})
    cb.close()
    os.remove(PF)


T_MV = NOW - 600
r3("R3 인출(스테이크 100 → 지갑) 원장에 아직 없음(빈 백필) = 100 (종전 200)", wallet_now=100, stake_snap=100, stake_now=0, records=[], expect=100)
r3("R3 인출 원장에 있음 = 100", wallet_now=100, stake_snap=100, stake_now=0,
   records=[(LOC_S, 100, NOW - 2000), (LOC_S, -100, T_MV), (LOC_W, 100, T_MV)], expect=100)
r3("R3 예치(지갑 100 → 스테이크) 원장에 아직 없음 = 100 (종전 0)", wallet_now=0, stake_snap=0, stake_now=100, records=[], expect=100)
r3("R3 예치 원장에 있음 = 100", wallet_now=0, stake_snap=0, stake_now=100,
   records=[(LOC_W, 100, NOW - 2000), (LOC_W, -100, T_MV), (LOC_S, 100, T_MV)], expect=100)
r3("R3 닫힌 계정(지금 없음) = 0 · 지갑 100 = 100", wallet_now=100, stake_snap=100, stake_now=None, records=[], expect=100)
r3("R3 다시 읽기 실패 = 스냅숏 값 + 스냅숏 시각 경계(종전 · 원장에 든 인출 = 100)", wallet_now=100, stake_snap=100, stake_now=0, fail=True,
   records=[(LOC_S, 100, NOW - 2000), (LOC_S, -100, T_MV), (LOC_W, 100, T_MV)], expect=100)
T.chk(all(m == "getMultipleAccounts" for _u, m in CALLS) and CALLS and CALLS[0][0] == "https://head.invalid",
      "R3 다시 읽기 = getMultipleAccounts(head 차선 먼저 · 계정 100개당 1콜)", CALLS[:6])
recon._rpc = _real_rpc
T.finish()
