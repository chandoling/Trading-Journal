from __future__ import annotations

import hashlib
import json
import re

import address_codec as ac
import chain_registry as reg

KIND = "chain_delta_tx"
VERSION = 1
EXTERNAL = "external"
_INT = re.compile(r"-?\d{1,80}")
_UID = re.compile(r"[0-9A-Za-z_.\-+/=]{1,220}")
HINTS = ("transfer", "swap", "stake", "program_in", "unknown", "")


class ContractError(ValueError):
    pass


def _int(v, what):
    if isinstance(v, bool) or not isinstance(v, str) or not _INT.fullmatch(v):
        raise ContractError(f"{what} 은 정수 문자열이어야 해요(float 금지): {v!r}")
    return int(v)


def _asset(chain, a, what):
    if not isinstance(a, dict):
        raise ContractError(f"{what}.asset 형식 오류")
    k = a.get("kind")
    if k == "native":
        dec = a.get("decimals")
        if dec is not None and int(dec) != reg.spec(chain).native_decimals:
            raise ContractError(f"{what}: 네이티브 자릿수 {dec} ≠ 레지스트리 {reg.spec(chain).native_decimals}")
        return ("native", None)
    if k != "token":
        raise ContractError(f"{what}.asset.kind 는 native|token")
    dec = a.get("decimals")
    if dec is not None and (isinstance(dec, bool) or not isinstance(dec, int) or not 0 <= dec <= 77):
        raise ContractError(f"{what}.asset.decimals 는 0~77 정수 또는 null(모름 — 18 로 지어내지 말 것)")
    try:
        return ("token", reg.asset_key(chain, "token", a.get("id")))
    except ValueError as e:
        raise ContractError(f"{what}.asset.id: {e}") from e


def validate(rec: dict) -> dict:
    if not isinstance(rec, dict) or rec.get("kind") != KIND:
        raise ContractError("chain_delta_tx 레코드가 아니에요")
    if rec.get("v") != VERSION:
        raise ContractError(f"모르는 계약 버전 v={rec.get('v')!r} — 이 코드는 v{VERSION} 만 읽어요(새 버전은 레지스트리·core 를 같이 올림)")
    chain = rec.get("chain")
    if not reg.is_nonevm(chain):
        raise ContractError(f"레지스트리에 없는 체인: {chain!r}")
    if rec.get("network", "mainnet") not in reg.NETWORKS:
        raise ContractError("메인넷만 받아요")
    uid = rec.get("tx_uid")
    if not isinstance(uid, str) or not _UID.fullmatch(uid):
        raise ContractError("tx_uid 형식 오류(영숫자·._-+/= 220자 이하)")
    if not isinstance(rec.get("txhash"), str) or not _UID.fullmatch(rec["txhash"]):
        raise ContractError("txhash 형식 오류")
    ts = rec.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0:
        raise ContractError(f"시각(ts) 없음·형식 오류: {ts!r} — 시각 모르는 거래는 보내지 말고 다시 예약")
    fin = rec.get("finality") or {}
    if fin.get("state") != "finalized":
        raise ContractError("확정(finalized) 안 된 거래는 원장에 보내지 않아요(대기 큐에 두기)")
    ex = rec.get("execution") or {}
    if ex.get("state") not in ("success", "failed"):
        raise ContractError("execution.state 는 success|failed")
    comp = rec.get("completeness") or {}
    if comp.get("details") is not True:
        raise ContractError("상세 미완(completeness.details) 레코드는 보내지 않아요 — 다시 예약하거나 gap 으로 남기기")
    owners = rec.get("owners")
    if not isinstance(owners, list) or not owners:
        raise ContractError("owners(방출 때 내 지갑 관점)가 비었어요")
    own = set()
    for o in owners:
        if not isinstance(o, str) or ":" in o or (chain != "btc" and _owner_norm(chain, o) != o) \
                or (chain == "btc" and not re.fullmatch(r"bw[0-9a-f]{32}", o)):
            raise ContractError(f"owners 에 원장 키가 아닌 값: {str(o)[:20]!r} — chain_registry.owner_key 로 정규화")
        own.add(o)
    if not isinstance(rec.get("deltas", []), list) or not isinstance(rec.get("fees", []), list):
        raise ContractError("deltas·fees 는 배열")
    deltas = []
    for i, d in enumerate(rec.get("deltas") or []):
        if not isinstance(d, dict) or d.get("owner") not in own:
            raise ContractError(f"deltas[{i}].owner 는 owners 안의 원장 키여야 해요")
        ak = _asset(chain, d.get("asset"), f"deltas[{i}]")
        v = _int(d.get("delta_base"), f"deltas[{i}].delta_base")
        a = d.get("asset") or {}
        deltas.append((d["owner"], ak, v, {"symbol": a.get("symbol"), "decimals": a.get("decimals")}))
    keys = [(o, ak) for o, ak, _v, _m in deltas]
    if len(keys) != len(set(keys)):
        raise ContractError("deltas 에 같은 (지갑, 자산) 줄이 두 번 — 한 줄로 합쳐 보내기")
    fees = []
    for i, f in enumerate(rec.get("fees") or []):
        if not isinstance(f, dict):
            raise ContractError(f"fees[{i}] 형식 오류")
        if (f.get("asset") or {}).get("kind") != "native":
            raise ContractError(f"fees[{i}]: 수수료는 네이티브만(이 판)")
        if f.get("included_in_deltas") is not True:
            raise ContractError(f"fees[{i}]: included_in_deltas=true 만(deltas 가 수수료 포함 실제 순변화)")
        p = f.get("payer")
        if p != EXTERNAL and p not in own:
            raise ContractError(f"fees[{i}].payer 는 owners 안의 원장 키 또는 'external'(스폰서·남)")
        fees.append((p, _int(f.get("amount_base"), f"fees[{i}].amount_base")))
    hint = ((rec.get("classification") or {}).get("hint") or "")
    if hint not in HINTS:
        raise ContractError(f"classification.hint 는 {HINTS}")
    return {"chain": chain, "uid": uid, "ts": ts, "owners": own, "deltas": deltas, "fees": fees,
            "failed": ex.get("state") == "failed", "trace_complete": ex.get("trace_complete") is not False,
            "hint": hint, "trusted": (rec.get("classification") or {}).get("trusted") is True}


def unknown_decimals(rec: dict) -> list:
    out = set()
    for d in (rec.get("deltas") or []) if isinstance(rec, dict) else ():
        a = (d or {}).get("asset") or {} if isinstance(d, dict) else {}
        if a.get("kind") == "token" and a.get("decimals") is None and str((d or {}).get("delta_base") or "0").lstrip("-") not in ("", "0"):
            out.add(str(a.get("id") or ""))
    return sorted(out)


WHY_DEC_UNKNOWN = "token_decimals_unknown"
WHY_SUM_MISMATCH = "token_sum_mismatch"
_BALANCE_WHY_CODES = frozenset((
    WHY_DEC_UNKNOWN, WHY_SUM_MISMATCH, "wallet_lt_ahead", "pending_details",
    "jetton_list_partial", "jetton_row_bad", "jetton_unverified", "jetton_balance_missing",
    "jetton_lt_ahead", "jetton_decimals_unknown", "jetton_wallet_missing",
))


def valid_decimals(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 77


def norm_counterparty(chain: str, text) -> str:
    if chain == "btc":
        return ac.btc_address(str(text or "")).get("address")
    return reg.owner_key(chain, str(text or ""))


def _mv_norm(chain, x) -> str:
    s = str(x or "").strip()
    if not s or len(s) > 200:
        return ""
    if chain == "btc" and re.fullmatch(r"bw[0-9a-f]{32}", s):
        return s
    try:
        return norm_counterparty(chain, s)
    except ValueError:
        return s


def _owner_norm(chain, o):
    try:
        return reg.owner_key(chain, o)
    except ValueError:
        return None


def to_core(rec: dict) -> dict:
    v = validate(rec)
    chain = v["chain"]
    net = {}
    meta = {}
    for o, ak, d, m in v["deltas"]:
        if d:
            net[(o, ak)] = net.get((o, ak), 0) + d
        if ak not in meta or (m.get("symbol") and not meta[ak].get("symbol")):
            meta[ak] = m
    fee = {}
    for p, amt in v["fees"]:
        if p != EXTERNAL and amt:
            fee[p] = fee.get(p, 0) + amt
    nat = ("native", None)
    econ = dict(net)
    for o, f in fee.items():
        econ[(o, nat)] = econ.get((o, nat), 0) + f
    econ = {k: x for k, x in econ.items() if x}
    chk = dict(econ)
    for o, f in fee.items():
        chk[(o, nat)] = chk.get((o, nat), 0) - f
    if {k: x for k, x in chk.items() if x} != {k: x for k, x in net.items() if x}:
        raise ContractError("수량 보존식 불일치(경제 레그 − 수수료 ≠ 순변화)")
    mine = v["owners"]
    cps, dest = [], {}
    for i, mv in enumerate(rec.get("movements") or []):
        if not isinstance(mv, dict):
            continue
        try:
            ak = _asset(chain, mv.get("asset"), f"movements[{i}]")
            amt = _int(mv.get("amount_base"), f"movements[{i}].amount_base")
        except ContractError:
            continue
        fk, tk = _mv_norm(chain, mv.get("from")), _mv_norm(chain, mv.get("to"))
        if tk and tk not in mine:
            if tk not in cps:
                cps.append(tk)
            if fk in mine and amt > 0:
                k = (fk, ak)
                cur = dest.get(k)
                if cur is None or amt > cur[1] or (amt == cur[1] and tk < cur[0]):
                    dest[k] = (tk, amt)
        elif fk and fk not in mine and fk not in cps:
            cps.append(fk)
    return {"chain": chain, "uid": v["uid"], "ts": v["ts"], "econ": econ, "fee": fee, "meta": meta, "cps": cps,
            "dest": {k: t for k, (t, _a) in dest.items()}, "failed": v["failed"], "trace_complete": v["trace_complete"],
            "hint": v["hint"], "trusted": v["trusted"], "owners": mine}


def legs_key(rec: dict) -> set:
    v = validate(rec)
    out = {(o, f"{ak[0]}:{ak[1] or ''}", str(d)) for o, ak, d, _m in v["deltas"] if d}
    for p, amt in v["fees"]:
        if p != EXTERNAL and amt:
            out.add((p, "__fee__", str(amt)))
    return out


def merge_ok(old: dict, new: dict) -> str:
    lo, ln = legs_key(old), legs_key(new)
    fo = (old.get("execution") or {}).get("state")
    fn = (new.get("execution") or {}).get("state")
    if fo != fn:
        return "conflict"
    if ln == lo or ln <= lo:
        return "same"
    if lo <= ln:
        return "grow"
    return "conflict"


def payload_digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:32]


def validate_balances(bal: dict, chain: str, owners: set, ownership_version: str = None) -> dict:
    why = []
    if not isinstance(bal, dict):
        return {"ok": False, "why": ["형식 오류"], "usable": {}}
    pw = bal.get("per_wallet")
    if not isinstance(pw, dict):
        why.append("per_wallet 없음")
        pw = {}
    if bal.get("_complete") is not True:
        raw = bal.get("_why")
        codes = list(dict.fromkeys(code for code in raw[:16]
                                  if isinstance(code, str) and len(code) <= 64 and code in _BALANCE_WHY_CODES))[:3] \
            if isinstance(raw, (list, tuple)) else []
        why.append("부분 결과(_complete 아님) — 자동 보정 보류" + (" [" + ", ".join(codes) + "]" if codes else ""))
    b = bal.get("_boundary")
    if not isinstance(b, dict) or b.get("kind") not in ("height", "checkpoint", "account_lt") or b.get("value") in (None, ""):
        why.append("경계(_boundary) 없음 — 같은 시점 비교 불가")
    if ownership_version is not None and bal.get("_ownership_version") != ownership_version:
        why.append("읽는 동안 내 지갑 집합이 바뀜 — 버리고 다시 읽기")
    for k9, m9 in ((bal.get("_meta") or {}).items() if isinstance(bal.get("_meta"), dict) else ()):
        d9 = m9[1] if isinstance(m9, (list, tuple)) and len(m9) >= 2 else None
        if d9 is not None and not valid_decimals(d9):
            why.append("_meta 자릿수는 0~77 정수 또는 null(모름)")
            break
    miss = sorted(set(owners or ()) - set(pw))
    if miss:
        why.append(f"지갑 {len(miss)}개 결과 없음(0 으로 보지 않음)")
    usable = {}
    for o, wb in pw.items():
        if o not in (owners or ()):
            why.append("등록 안 된 지갑 결과가 섞임")
            continue
        if not isinstance(wb, dict):
            why.append("지갑 결과 형식 오류")
            continue
        un = set(map(str, ((bal.get("_unobserved") or {}).get(o) or [])))
        out = {}
        for k, x in wb.items():
            if not (isinstance(k, tuple) and len(k) == 2 and k[0] in ("native", "token")):
                why.append("자산 키는 ('native', None) 또는 ('token', 원장 토큰 키)")
                continue
            if isinstance(x, bool) or not isinstance(x, int) or x < 0:
                why.append("잔고는 0 이상 정수(base 단위)")
                continue
            if str(k[1]) in un:
                continue
            out[k] = x
        usable[o] = out
    return {"ok": not why, "why": why, "usable": usable}
