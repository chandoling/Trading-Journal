from __future__ import annotations

import importlib.util
import os
import re
from urllib.parse import quote

import address_codec as ac

NETWORKS = ("mainnet",)
CFG_KEY = "chain_wallets"
CFG_CHAIN_KEY = "nonevm"
MAX_CHAIN_WALLETS = 100


class ChainSpec:

    def __init__(self, key, name, native_symbol, native_decimals, module, *, cg_native, tx_url, addr_url,
                 key_env=None, key_policy="none", explorer_verified=False, unit_order="", order_kind="height"):
        self.key = key
        self.name = name
        self.native_symbol = native_symbol
        self.native_decimals = int(native_decimals)
        self.module = module
        self.cg_native = cg_native
        self.tx_url = tx_url
        self.addr_url = addr_url
        self.key_env = key_env
        self.key_policy = key_policy
        self.explorer_verified = explorer_verified
        self.order_kind = order_kind

    @property
    def stream(self) -> str:
        return self.key

    @property
    def unit(self) -> str:
        return "tj-" + self.key

    @property
    def cursor_file(self) -> str:
        return f"cursor_{self.key}.json"

    @property
    def emitted_file(self) -> str:
        return f"emitted_{self.key}.json"


SPECS = {
    "tron": ChainSpec("tron", "Tron", "TRX", 6, "tron_watch", cg_native="tron",
                      tx_url="https://tronscan.org/#/transaction/{}", addr_url="https://tronscan.org/#/address/{}",
                      key_env="TJ_TRONGRID_KEY", key_policy="recommended", order_kind="height"),
    "sui": ChainSpec("sui", "Sui", "SUI", 9, "sui_watch", cg_native="sui",
                     tx_url="https://suiscan.xyz/mainnet/tx/{}", addr_url="https://suiscan.xyz/mainnet/account/{}",
                     order_kind="checkpoint"),
    "ton": ChainSpec("ton", "TON", "TON", 9, "ton_watch", cg_native="the-open-network",
                     tx_url="https://tonviewer.com/transaction/{}", addr_url="https://tonviewer.com/{}",
                     key_env="TJ_TONCENTER_KEY", key_policy="recommended", order_kind="account_lt"),
    "btc": ChainSpec("btc", "Bitcoin", "BTC", 8, "btc_watch", cg_native="bitcoin",
                     tx_url="https://mempool.space/tx/{}", addr_url="https://mempool.space/address/{}",
                     order_kind="height"),
}
CHAINS = tuple(SPECS)
FORCE_AVAILABLE = set()


def spec(chain: str) -> ChainSpec:
    s = SPECS.get(str(chain or ""))
    if s is None:
        raise ValueError(f"비EVM 레지스트리에 없는 체인: {chain!r}")
    return s


def is_nonevm(chain) -> bool:
    return str(chain or "") in SPECS


def available(chain: str) -> bool:
    if chain in FORCE_AVAILABLE:
        return True
    s = SPECS.get(chain)
    if s is None:
        return False
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, s.module + ".py")):
        return True
    try:
        return importlib.util.find_spec(s.module) is not None
    except (ImportError, ValueError):
        return False


def native_decimals(chain: str, default=None):
    s = SPECS.get(str(chain or ""))
    return s.native_decimals if s else default


def native_symbol(chain: str, default=None):
    s = SPECS.get(str(chain or ""))
    return s.native_symbol if s else default


def display_name(chain: str) -> str:
    s = SPECS.get(str(chain or ""))
    return s.name if s else str(chain or "")


def owner_key(chain: str, text: str, network: str = "mainnet") -> str:
    if network not in NETWORKS:
        raise ValueError("지금은 메인넷 지갑만 받아요")
    if chain == "tron":
        return ac.tron_key(text)
    if chain == "sui":
        return ac.sui_key(text)
    if chain == "ton":
        return ac.ton_key(text, network)
    if chain == "btc":
        return ac.btc_wallet_id(ac.btc_address(text, network)["address"])
    raise ValueError(f"비EVM 레지스트리에 없는 체인: {chain!r}")


def btc_source(entry: dict, network: str = "mainnet") -> dict:
    mode = str(entry.get("mode") or ("descriptor" if entry.get("descriptor") else "address"))
    if mode == "address":
        a = ac.btc_address(str(entry.get("address") or ""), network)
        return {"mode": "address", "key": ac.btc_wallet_id(a["address"]), "address": a["address"], "script": a["script"],
                "script_type": a["type"], "branches": [], "display": a["address"]}
    if mode == "descriptor":
        d = ac.btc_descriptor(str(entry.get("descriptor") or ""), network)
        gl = entry.get("gap_limit", 20)
        if isinstance(gl, bool) or not isinstance(gl, int) or not 1 <= gl <= 1000:
            raise ValueError("gap_limit 은 1~1000 정수예요(기본 20)")
        return {"mode": "descriptor", "key": ac.btc_wallet_id(d["descriptor"]), "descriptor": d["descriptor"],
                "script_type": d["script_type"], "branches": d["branches"], "gap_limit": gl, "display": ac.btc_mask(d["descriptor"])}
    raise ValueError("BTC 지갑 mode 는 address 또는 descriptor 예요")


_KC_TRON = re.compile(r"41[0-9a-fA-F]{40}|T[1-9A-HJ-NP-Za-km-z]{33}")
_KC_SUI = re.compile(r"0x[0-9a-fA-F]{64}")
_KC_TON = re.compile(r"-?[01]_[0-9a-f]{64}|-?[01]:[0-9a-fA-F]{64}|[A-Za-z0-9+/_-]{48}")
_KC_BTCW = re.compile(r"bw[0-9a-f]{32}")
_KC_BTC = re.compile(r"(?:bc1|BC1)[02-9ac-hj-np-zAC-HJ-NP-Z]{8,87}|[13][1-9A-HJ-NP-Za-km-z]{25,34}")


def key_parse(text):
    s = str(text or "").strip()
    if not s or len(s) > 100:
        return None
    try:
        if _KC_TRON.fullmatch(s):
            return "tron", ac.tron_key(s)
        if _KC_SUI.fullmatch(s):
            return "sui", ac.sui_key(s)
        if _KC_TON.fullmatch(s):
            return "ton", ac.ton_key(s)
        if _KC_BTCW.fullmatch(s):
            return "btc", s
        if _KC_BTC.fullmatch(s):
            return "btc", ac.btc_address(s)["address"]
    except ValueError:
        return None
    return None


def key_chain(text):
    r = key_parse(text)
    return r[0] if r else None


def display_owner(chain: str, key: str) -> str:
    if chain == "tron":
        return ac.tron_display(key)
    if chain == "ton":
        return ac.ton_friendly(key, bounceable=False)
    return str(key)


def asset_key(chain: str, kind: str, ident) -> str:
    if kind == "native":
        return None
    if kind != "token":
        raise ValueError(f"자산 종류는 native|token: {kind!r}")
    if chain == "tron":
        return ac.tron_key(ident)
    if chain == "sui":
        t = ac.sui_type_canonical(ident)
        if t == ac.SUI_NATIVE_TYPE:
            raise ValueError("0x2::sui::SUI 는 네이티브(kind native)로 보내세요 — 토큰 칸에 넣으면 같은 SUI 가 두 자산이 됩니다")
        return ac.sui_asset_key(t)
    if chain == "ton":
        return ac.ton_key(ident)
    if chain == "btc":
        raise ValueError("BTC 는 네이티브만 받아요(Ordinals·Runes·BRC-20 은 범위 밖)")
    raise ValueError(f"비EVM 레지스트리에 없는 체인: {chain!r}")


def asset_ident(chain: str, key: str):
    if key is None:
        return None
    if chain == "tron":
        return ac.tron_display(key)
    if chain == "sui":
        return ac.sui_asset_type(key)
    if chain == "ton":
        return ac.ton_raw(key)
    return key


def make_location(chain: str, key: str) -> str:
    if ":" in str(key) or not key:
        raise ValueError("원장 키에 콜론이 있으면 안 돼요(위치 판정이 깨짐)")
    return f"wallet:{chain}:{key}"


def parse_location(loc: str):
    parts = str(loc or "").split(":", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]


_SAFE_ID = re.compile(r"[0-9A-Za-z_\-+/=:.]{1,200}")


def tx_url(chain: str, txhash: str) -> str:
    s = SPECS.get(str(chain or ""))
    t = str(txhash or "")
    if s is None or not _SAFE_ID.fullmatch(t):
        return ""
    if s.key == "ton" and t.count(".") == 2:
        t = t.rsplit(".", 1)[1]
    return s.tx_url.format(quote(t, safe=""))


def address_url(chain: str, display: str) -> str:
    s = SPECS.get(str(chain or ""))
    a = str(display or "")
    if s is None or not _SAFE_ID.fullmatch(a) or a.startswith("bw"):
        return ""
    return s.addr_url.format(quote(a, safe=":"))


def wallets(cfg: dict, chain: str = None, with_errors: bool = False):
    rows, errs, seen = [], [], set()
    lst = (cfg or {}).get(CFG_KEY) if isinstance(cfg, dict) else None
    for i, w in enumerate(lst if isinstance(lst, list) else []):
        try:
            if not isinstance(w, dict):
                raise ValueError("지갑 줄 형식 오류")
            c = str(w.get("chain") or "")
            if c not in SPECS:
                raise ValueError(f"지원하지 않는 체인: {c!r}")
            if chain is not None and c != chain:
                continue
            net = str(w.get("network") or "mainnet")
            if net not in NETWORKS:
                raise ValueError("메인넷만 받아요")
            if c == "btc":
                src = btc_source(w, net)
                key, disp, mode = src["key"], src["display"], src["mode"]
            else:
                key = owner_key(c, str(w.get("address") or ""), net)
                disp, mode = display_owner(c, key), "address"
            if (c, net, key) in seen:
                continue
            seen.add((c, net, key))
            rows.append({"chain": c, "network": net, "key": key, "display": disp, "label": str(w.get("label") or ""),
                         "mode": mode, "entry": w})
        except ValueError as e:
            errs.append((i, str(e)))
    return (rows, errs) if with_errors else rows


def owners(cfg: dict, chain: str) -> set:
    return {r["key"] for r in wallets(cfg, chain)}


def ownership_version(cfg: dict, chain: str) -> str:
    import hashlib
    return hashlib.sha256(("|".join(sorted(owners(cfg, chain)))).encode()).hexdigest()[:16]


def configured_chains(cfg: dict) -> list:
    return sorted({r["chain"] for r in wallets(cfg)})


def present_streams(inbox_dir: str, state_dir: str = None) -> list:
    out = []
    for c, s in SPECS.items():
        d = os.path.join(inbox_dir, s.stream)
        st = [os.path.join(state_dir, s.cursor_file), os.path.join(state_dir, s.emitted_file)] if state_dir else []
        if os.path.isdir(d) or any(os.path.exists(p) for p in st):
            out.append(c)
    return out


class ProviderCapability:

    def __init__(self, chain, provider, role, transport, *, keyless=False, key_env=None, supported=True, verified=False,
                 verified_at=None, history_from=None, rate_hint=None, source_url="", note=""):
        self.chain, self.provider, self.role, self.transport = chain, provider, role, transport
        self.keyless, self.key_env, self.supported, self.verified = keyless, key_env, supported, verified
        self.verified_at, self.history_from, self.rate_hint = verified_at, history_from, rate_hint
        self.source_url, self.note = source_url, note

    def as_dict(self) -> dict:
        return dict(self.__dict__)


CAPABILITIES = [
    ProviderCapability("tron", "trongrid", "address_history", "rest", keyless=True, key_env="TJ_TRONGRID_KEY",
                       rate_hint="무키 응답은 하나 운영 보장 아님 — 키 권장(한도는 요금제·정책별, 고정값 금지)",
                       source_url="https://developers.tron.network/reference/rate-limits"),
    ProviderCapability("tron", "trongrid", "tx_detail", "rest", keyless=True, key_env="TJ_TRONGRID_KEY",
                       note="/walletsolidity/gettransactionbyid + gettransactioninfobyid — 빈 영수증 = 일시 지연(재시도)",
                       source_url="https://developers.tron.network/docs/confirmation-semantics"),
    ProviderCapability("tron", "trongrid", "balance", "rest", keyless=True, key_env="TJ_TRONGRID_KEY",
                       note="계정 TRC-20 목록 = 발견 힌트 · 확정 잔고는 balanceOf(solidified) — 과거 블록 잔고 대용 금지"),
    ProviderCapability("tron", "alchemy", "tx_detail", "rest", key_env="TJ_ALCHEMY_KEY", supported=True,
                       note="Tron HTTP·Solidity 지원표 등재 — 무료 권한 미확인(EVM JSON-RPC 호출기로 부르지 말 것)",
                       source_url="https://www.alchemy.com/docs/reference/tron-api-faq"),
    ProviderCapability("sui", "sui_graphql", "address_history", "graphql", keyless=True,
                       note="affectedAddress 필터 · serviceConfig.availableRange 로 보존 범위 확인 — 범위 밖 시작일은 부분 coverage",
                       source_url="https://docs.sui.io/references/sui-api"),
    ProviderCapability("sui", "sui_graphql", "balance", "graphql", keyless=True,
                       note="totalBalance(coin 객체 + address balance) · 한 checkpoint scope 로 끝까지 page"),
    ProviderCapability("sui", "alchemy", "balance", "grpc", key_env="TJ_ALCHEMY_KEY", supported=False,
                       note="Alchemy Sui = gRPC(HTTP/2·protobuf) — 표준 라이브러리만 쓰는 이 저장소에선 미지원(새 의존성 결정 필요)",
                       source_url="https://www.alchemy.com/docs/reference/sui-grpc-quickstart"),
    ProviderCapability("ton", "toncenter", "address_history", "rest", keyless=True, key_env="TJ_TONCENTER_KEY",
                       rate_hint="무키 1rps · 무료 키 10rps(같은 network 키들이 한도 공유 — 키 여러 개로 더하지 말 것)",
                       source_url="https://docs.ton.org/api/rate-limit"),
    ProviderCapability("ton", "toncenter", "balance", "rest", keyless=True, key_env="TJ_TONCENTER_KEY",
                       note="native account + jetton wallets(master·owner 검증) — 같은 경계 고정 못 하면 non_atomic(자동 보정 보류)"),
    ProviderCapability("btc", "esplora", "address_history", "rest", keyless=True,
                       note="주소/scripthash 이력(last_seen_txid 로 25건씩) — xpub API 아님(HD 파생은 로컬) · 무료 QPS 보장 없음",
                       source_url="https://github.com/Blockstream/esplora/blob/master/API.md"),
    ProviderCapability("btc", "esplora", "balance", "rest", keyless=True, note="UTXO 합(txid,vout 중복 제거) · confirmed/pending 분리"),
    ProviderCapability("btc", "ankr", "address_history", "rest", key_env="TJ_ANKR_KEY", supported=False,
                       note="BTC Blockbook = Premium(2026-08-31 변경기록) — 무료 경로 제외",
                       source_url="https://www.ankr.com/docs/changelog/public-tier-chains-2026-08-31/"),
]


def capabilities(chain: str, role: str = None, usable_only: bool = True) -> list:
    return [c for c in CAPABILITIES if c.chain == chain and (role is None or c.role == role) and (not usable_only or c.supported)]


class ChainAdapter:

    chain = None

    def __init__(self, cfg: dict):
        if self.chain not in SPECS:
            raise ValueError("ChainAdapter.chain 을 레지스트리 체인으로 정하세요")
        self.cfg = cfg or {}
        self.spec = SPECS[self.chain]
        self.native_symbol = self.spec.native_symbol
        self.native_decimals = self.spec.native_decimals

    def canonical_owner(self, text, network="mainnet"):
        return owner_key(self.chain, text, network)

    def canonical_asset(self, kind, identifier):
        return asset_key(self.chain, kind, identifier)

    def make_location(self, owner):
        return make_location(self.chain, owner)

    def parse_location(self, text):
        return parse_location(text)

    def get_capabilities(self, provider=None):
        return [c for c in capabilities(self.chain, usable_only=False) if provider is None or c.provider == provider]

    def canonical_txid(self, text):
        raise NotImplementedError

    def discovery_query(self, owner, lane):
        raise NotImplementedError

    def discover_page(self, scope, query, cursor):
        raise NotImplementedError

    def fetch_and_normalize(self, tx_ref, owners):
        raise NotImplementedError

    def fetch_balances(self, owners, boundary, tokens=None):
        raise NotImplementedError

    state = None

    def lane_safe(self, owner, lane) -> dict:
        st = self.state
        s = ((getattr(st, "d", None) or {}).get("lanes") or {}).get(f"{lane}:{owner}") if st is not None else None
        s = (s or {}).get("safe") if isinstance(s, dict) else None
        return dict(s) if isinstance(s, dict) else {}

    def lane_done(self, owner, lane, query):
        return None
