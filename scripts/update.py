from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "breadth.json"
REVIEW_FILE = ROOT / "review.md"
QUOTE_URL = "https://futsseapi.eastmoney.com/list/trans/block/risk/mk0830"
FIELDS = "name,p,zdf,vol,ccl,rz,tjd,cje,zde,o,h,l,zf,zjsj,zt,dt,dm,sc,tag,uid,zsjd"
COMMODITY_EXCHANGES = {113, 114, 115, 142, 225}  # SHFE, DCE, CZCE, INE, GFEX


def get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://qhweb.eastmoney.com/quote",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_rows() -> list[dict]:
    params = {
        "orderBy": "",
        "sort": "",
        "pageSize": "999",
        "pageIndex": "0",
        "specificContract": "true",
        "platform": "zbPC",
        "field": FIELDS,
    }
    url = QUOTE_URL + "?" + urllib.parse.urlencode(params)
    data = get_json(url)
    rows = data.get("list") or []
    return [r for r in rows if r.get("sc") in COMMODITY_EXCHANGES]


def same_price(a, b) -> bool:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    return abs(a - b) < 1e-9


def summarize(rows: list[dict]) -> dict:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    up = down = flat = limit_up = limit_down = 0
    for r in rows:
        zdf = r.get("zdf")
        price = r.get("p")
        if isinstance(zdf, (int, float)) and zdf > 0:
            up += 1
        elif isinstance(zdf, (int, float)) and zdf < 0:
            down += 1
        else:
            flat += 1
        if same_price(price, r.get("zt")):
            limit_up += 1
        if same_price(price, r.get("dt")):
            limit_down += 1
    signal = ""
    if up < 15:
        signal = f"上涨家数过低：{up}"
    elif up > 60:
        signal = f"上涨家数过高：{up}"
    return {
        "date": now.date().isoformat(),
        "updated_at": now.strftime("%H:%M:%S"),
        "total": len(rows),
        "up": up,
        "down": down,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "flat": flat,
        "signal": signal,
    }


def load_history() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_history(summary: dict) -> list[dict]:
    history = load_history()
    history = [x for x in history if x.get("date") != summary["date"]]
    history.append(summary)
    history.sort(key=lambda x: x.get("date", ""))
    DATA_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return history


def append_review(summary: dict) -> None:
    if REVIEW_FILE.exists():
        text = REVIEW_FILE.read_text(encoding="utf-8")
    else:
        text = "# 每日复盘\n\n"
    marker = f"## {summary['date']}"
    block = (
        f"{marker}\n\n"
        f"- 上涨主力合约：{summary['up']}\n"
        f"- 下跌主力合约：{summary['down']}\n"
        f"- 涨停：{summary['limit_up']}\n"
        f"- 跌停：{summary['limit_down']}\n"
        f"- 不涨不跌：{summary['flat']}\n"
        f"- 样本数：{summary['total']}\n"
        f"- 信号：{summary['signal'] or '无'}\n\n"
    )
    if marker in text:
        before = text.split(marker, 1)[0].rstrip() + "\n\n"
        rest = text.split(marker, 1)[1]
        after = rest.split("\n## ", 1)
        tail = "\n## " + after[1] if len(after) == 2 else ""
        text = before + block + tail.lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + block
    REVIEW_FILE.write_text(text, encoding="utf-8")


def notify_wechat(summary: dict) -> None:
    webhook = os.getenv("WECHAT_WEBHOOK")
    if not webhook:
        return
    content = (
        f"期货期权每日汇总 {summary['date']}\n"
        f"上涨：{summary['up']}，下跌：{summary['down']}，平盘：{summary['flat']}\n"
        f"涨停：{summary['limit_up']}，跌停：{summary['limit_down']}\n"
        f"信号：{summary['signal'] or '无'}"
    )
    body = json.dumps({"msgtype": "text", "text": {"content": content}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def main() -> int:
    rows = fetch_rows()
    if not rows:
        print("no rows fetched", file=sys.stderr)
        return 1
    summary = summarize(rows)
    save_history(summary)
    append_review(summary)
    notify_wechat(summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
