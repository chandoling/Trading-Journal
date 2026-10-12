#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import chain_event as ce

OWNER = "synthetic_owner"
GENERIC = "부분 결과(_complete 아님) — 자동 보정 보류"
GOOD = {"per_wallet": {OWNER: {("native", None): 123}},
        "_complete": True, "_boundary": {"kind": "account_lt", "value": "lt:synthetic_owner=1"}}


def validate(why, complete=False):
    return ce.validate_balances(dict(GOOD, _complete=complete, _why=why), "ton", {OWNER})


def detail(v):
    return next(s for s in v["why"] if s.startswith(GENERIC))


v = validate(["jetton_decimals_unknown"])
T.chk("jetton_decimals_unknown" in detail(v), "D1 incomplete diagnostic retains adapter reason", v)
T.chk(v["ok"] is False and v["usable"] == GOOD["per_wallet"] and len(v["why"]) == 1,
      "D2 hold and usable balances unchanged", v)
bad = dict(GOOD, _complete=False, _why=["jetton_decimals_unknown"],
           per_wallet=None, _boundary=None, _ownership_version="old")
v = ce.validate_balances(bad, "ton", {OWNER}, "new")
T.chk("jetton_decimals_unknown" in " · ".join(v["why"][:3]),
      "D3 detail remains inside Core first-three-reasons message", v)
T.chk(v["ok"] is False and v["usable"] == {} and len(v["why"]) == 5,
      "D4 additional validation failures retain order and count", v)

class NoStringify:
    def __str__(self):
        raise AssertionError("untrusted objects must not be converted to strings")


for i, raw in enumerate((None, "jetton_decimals_unknown", 1, True, {},
                         {"jetton_decimals_unknown": True}, {"jetton_decimals_unknown"},
                         NoStringify(), iter(["jetton_decimals_unknown"]))):
    v = validate(raw)
    T.chk(v == {"ok": False, "why": [GENERIC], "usable": GOOD["per_wallet"]},
          f"D5 malformed _why container {i} retains generic hold", v)

unsafe = ["jetton_decimals_unknown\nFORGED", "jetton_decimals_unknown\r",
          "jetton_decimals_unknown\x00", "\x1b[31mjetton_decimals_unknown",
          "https://provider.invalid/?api_key=synthetic", "api_key_synthetic_secret",
          "x" * 1000000, "jetton_decimals_unknown extra", "토큰_오류", "",
          None, {}, [], 7, NoStringify(), "jetton_decimals_unknown"]
v = validate(unsafe)
T.chk(detail(v) == GENERIC + " [jetton_decimals_unknown]",
      "D6 reject payloads, unknown identifiers, huge strings and control characters", v)
T.chk(v["ok"] is False and v["usable"] == GOOD["per_wallet"],
      "D7 hostile diagnostics do not affect hold or amounts", v)
v = validate(["jetton_decimals_unknown"] * 6 + ["pending_details", "wallet_lt_ahead", "jetton_list_partial"])
T.chk(detail(v) == GENERIC + " [jetton_decimals_unknown, pending_details, wallet_lt_ahead]",
      "D8 at most three distinct codes in adapter order", v)
v = validate([None] * 16 + ["jetton_decimals_unknown"] * 10000)
T.chk(v["why"] == [GENERIC], "D9 inspect at most sixteen inputs", v)
v = validate(("token_decimals_unknown", "token_sum_mismatch"))
T.chk(detail(v) == GENERIC + " [token_decimals_unknown, token_sum_mismatch]",
      "D10 known Sui code tuple supported", v)

for i, raw in enumerate(([], ["jetton_decimals_unknown"], unsafe, NoStringify())):
    v = validate(raw, complete=True)
    T.chk(v == {"ok": True, "why": [], "usable": GOOD["per_wallet"]},
          f"D11 complete response shape and acceptance unchanged {i}", v)
for i, raw in enumerate((None, [], "bad", 0, True, NoStringify())):
    v = ce.validate_balances(raw, "ton", {OWNER})
    T.chk(v == {"ok": False, "why": ["형식 오류"], "usable": {}},
          f"D12 non-dict input unchanged {i}", v)

unobs = dict(GOOD, _complete=False, _why=["jetton_decimals_unknown"],
             per_wallet={OWNER: {("native", None): 123, ("token", "hidden"): 1000}},
             _unobserved={OWNER: ["hidden"]})
v = ce.validate_balances(unobs, "ton", {OWNER})
T.chk(v["ok"] is False and v["usable"] == GOOD["per_wallet"],
      "D13 unobserved token filtering unchanged", v)
T.chk(len(detail(validate(["jetton_decimals_unknown"] * 100000))) <= len(GENERIC) + 3 * 64 + 6,
      "D14 diagnostic output length bounded")
T.finish()
