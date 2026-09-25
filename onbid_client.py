from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ORIGIN = "https://www.onbid.co.kr"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PBANC_RE = re.compile(r"^\d{6}-\d{5}-\d{2}$")
CLTR_RE = re.compile(r"^\d{4}-\d{4}-\d{6}$")

DEFAULT_TRACKED = [
    {"originalPbanc": "202412-49115-01", "alias": None, "cltrMngNo": None, "note": None},
    {
        "originalPbanc": "202502-05480-00",
        "alias": "202502-05482-00",
        "cltrMngNo": "2025-0200-008474",
        "note": "온비드 공고번호가 202502-05482-00으로 확인됨",
    },
    {
        "originalPbanc": "202503-06201-00",
        "alias": "202503-09207-00",
        "cltrMngNo": "2025-0300-013755",
        "note": "온비드 공고번호가 202503-09207-00, 물건관리번호 2025-0300-013755로 확인됨",
    },
    {"originalPbanc": "202503-04909-00", "alias": None, "cltrMngNo": None, "note": None},
    {"originalPbanc": "202503-10391-00", "alias": None, "cltrMngNo": None, "note": None},
    {
        "originalPbanc": "202504-19911-00",
        "alias": "202504-15911-00",
        "cltrMngNo": "2025-0400-025470",
        "note": "온비드 공고번호가 202504-15911-00으로 확인됨",
    },
    {"originalPbanc": "202505-17622-01", "alias": None, "cltrMngNo": None, "note": None},
    {"originalPbanc": "202506-23542-00", "alias": None, "cltrMngNo": None, "note": None},
    {"originalPbanc": "202607-25061-00", "alias": None, "cltrMngNo": None, "note": None},
    {"originalPbanc": "202601-55586-00", "alias": None, "cltrMngNo": None, "note": None},
    {
        "originalPbanc": "202605-19077-00",
        "alias": "202405-19077-00",
        "cltrMngNo": "2023-0600-030773",
        "note": "온비드 공고번호가 202405-19077-00으로 확인됨",
    },
    {"originalPbanc": "202509-32873-00", "alias": None, "cltrMngNo": None, "note": None},
    {"originalPbanc": "202503-09775-00", "alias": None, "cltrMngNo": None, "note": None},
]

TRACKED_FILE = Path(__file__).resolve().parent / "data" / "tracked.json"

SNAPSHOT_CANDIDATES = [
    Path(__file__).resolve().parent / "data" / "snapshot.json",
]


class TrackedError(ValueError):
    """공고번호 또는 물건관리번호 입력이 저장 규칙을 벗어난 경우."""


def normalize_tracked(raw: dict[str, Any]) -> dict[str, Any]:
    original = str(raw.get("originalPbanc") or "").strip()
    alias = str(raw.get("alias") or "").strip() or None
    cltr = str(raw.get("cltrMngNo") or "").strip() or None
    note = str(raw.get("note") or "").strip() or None
    if not PBANC_RE.fullmatch(original):
        raise TrackedError("표 공고번호 형식이 아닙니다. 예: 202503-06201-00")
    if alias and not PBANC_RE.fullmatch(alias):
        raise TrackedError("온비드 공고번호 형식이 아닙니다. 예: 202503-09207-00")
    if alias == original:
        alias = None
    if cltr and not CLTR_RE.fullmatch(cltr):
        raise TrackedError("물건관리번호 형식이 아닙니다. 예: 2025-0300-013755")
    numbers = _clean_item_numbers(raw.get("cltrMngNos"), cltr)
    if note is None and (alias or cltr or numbers):
        parts = []
        if alias:
            parts.append(f"온비드 공고번호가 {alias}으로 확인됨")
        if numbers:
            parts.append("물건관리번호 " + ", ".join(numbers))
        elif cltr:
            parts.append(f"물건관리번호 {cltr}")
        note = ", ".join(parts)
    return {
        "originalPbanc": original,
        "alias": alias,
        "cltrMngNo": cltr,
        "cltrMngNos": numbers,
        "note": note,
    }


def _clean_item_numbers(raw_numbers: Any, manual: str | None) -> list[str]:
    numbers: list[str] = []
    if isinstance(raw_numbers, str):
        raw_numbers = [part.strip() for part in raw_numbers.split(",")]
    if isinstance(raw_numbers, list):
        for value in raw_numbers:
            number = str(value or "").strip()
            if not number or number in numbers:
                continue
            if not CLTR_RE.fullmatch(number):
                raise TrackedError("물건관리번호 형식이 아닙니다. 예: 2025-0300-013755")
            numbers.append(number)
    if manual and manual not in numbers:
        numbers.insert(0, manual)
    return numbers


def load_tracked() -> list[dict[str, Any]]:
    path = TRACKED_FILE
    if not path.exists():
        items = [normalize_tracked(item) for item in DEFAULT_TRACKED]
        save_tracked(items)
        return items
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    raw_items = data.get("tracked") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raise TrackedError("추적 목록 파일 형식이 올바르지 않습니다.")
    return [normalize_tracked(item) for item in raw_items]


def save_tracked(items: list[dict[str, Any]]) -> Path:
    normalized = [normalize_tracked(item) for item in items]
    path = TRACKED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tracked": normalized}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def upsert_tracked(
    raw: dict[str, Any],
    replace_original: str | None = None,
    *,
    create_only: bool = False,
) -> list[dict[str, Any]]:
    entry = normalize_tracked(raw)
    items = load_tracked()
    target = (replace_original or "").strip() or entry["originalPbanc"]
    index = next((i for i, item in enumerate(items) if item["originalPbanc"] == target), None)
    if create_only and index is not None:
        raise TrackedError(f"이미 등록된 표 공고번호입니다: {entry['originalPbanc']}")
    if index is None and replace_original:
        raise TrackedError(f"수정할 공고를 찾지 못했습니다: {replace_original}")
    duplicate = next(
        (
            item
            for i, item in enumerate(items)
            if item["originalPbanc"] == entry["originalPbanc"] and i != index
        ),
        None,
    )
    if duplicate:
        raise TrackedError(f"이미 등록된 표 공고번호입니다: {entry['originalPbanc']}")
    if index is not None and "cltrMngNos" not in raw:
        previous = items[index].get("cltrMngNos") or []
        merged = list(previous)
        if entry.get("cltrMngNo") and entry["cltrMngNo"] not in merged:
            merged.insert(0, entry["cltrMngNo"])
        entry["cltrMngNos"] = merged
    if index is None:
        items.append(entry)
    else:
        items[index] = entry
    save_tracked(items)
    return items


def delete_tracked(original: str) -> list[dict[str, Any]]:
    key = original.strip()
    items = load_tracked()
    kept = [item for item in items if item["originalPbanc"] != key]
    if len(kept) == len(items):
        raise TrackedError(f"삭제할 공고를 찾지 못했습니다: {key}")
    save_tracked(kept)
    return kept


def alias_items_for(tracked: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
    items = load_tracked() if tracked is None else tracked
    mapping: dict[str, list[str]] = {}
    for item in items:
        numbers = list(item.get("cltrMngNos") or [])
        manual = item.get("cltrMngNo")
        if manual and manual not in numbers:
            numbers.insert(0, manual)
        if numbers:
            mapping[item.get("alias") or item["originalPbanc"]] = numbers
    return mapping


def remember_item_numbers(original: str, items: list[dict[str, Any]]) -> None:
    numbers: list[str] = []
    for item in items:
        number = str(item.get("cltrMngNo") or "").strip()
        if number and number not in numbers:
            numbers.append(number)
    if not numbers:
        return
    tracked = load_tracked()
    changed = False
    for entry in tracked:
        if entry["originalPbanc"] != original:
            continue
        manual = entry.get("cltrMngNo")
        merged = list(numbers)
        if manual and manual not in merged:
            merged.insert(0, manual)
        if entry.get("cltrMngNos") != merged:
            entry["cltrMngNos"] = merged
            changed = True
        if not manual:
            entry["cltrMngNo"] = merged[0]
            changed = True
    if changed:
        save_tracked(tracked)


def snapshot_path() -> Path:
    for path in SNAPSHOT_CANDIDATES:
        if path.exists():
            return path
    return SNAPSHOT_CANDIDATES[0]


def load_snapshot() -> dict[str, Any]:
    path = snapshot_path()
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_snapshot(data: dict[str, Any]) -> Path:
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_date(value: str | None) -> str:
    if not value:
        return "—"
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    return match.group(0) if match else value


def format_won(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}원"


def item_url(item: dict[str, Any]) -> str:
    params = []
    for key in (
        "cltrScrnGrpCd",
        "cltrPrptDivCd",
        "onbidCltrno",
        "onbidPbancNo",
        "pbctNo",
        "pbctCdtnNo",
    ):
        if item.get(key):
            params.append(f"{key}={item[key]}")
    return (
        f"{ORIGIN}/op/cltrpbancinf/cltrdtl/CltrDtlController/mvmnCltrDtl.do?"
        + "&".join(params)
    )


def flatten_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ann in snapshot.get("announcements") or []:
        if not ann.get("found") or not ann.get("items"):
            rows.append(
                {
                    "originalPbanc": ann.get("originalPbanc"),
                    "pbancMngNo": ann.get("currentPbanc"),
                    "cltrMngNo": "",
                    "name": ann.get("title") or "온비드에서 현재 조회되지 않는 공고입니다",
                    "status": "조회불가",
                    "round": "",
                    "bidStart": format_date(ann.get("bidStart")),
                    "bidEnd": format_date(ann.get("bidEnd")),
                    "minBid": None,
                    "appraisal": None,
                    "org": ann.get("org") or "",
                    "url": ann.get("onbidUrl") or "",
                    "note": ann.get("note") or "",
                }
            )
            continue
        for item in ann["items"]:
            note = ann.get("note") or ""
            if ann.get("originalPbanc") != ann.get("currentPbanc"):
                note = f"표 {ann['originalPbanc']} → 온비드 {ann['currentPbanc']}"
            rows.append(
                {
                    "originalPbanc": ann.get("originalPbanc"),
                    "pbancMngNo": item.get("pbancMngNo") or ann.get("currentPbanc"),
                    "cltrMngNo": item.get("cltrMngNo") or "",
                    "name": item.get("name") or "",
                    "status": item.get("status") or "",
                    "round": item.get("round") or "",
                    "bidStart": format_date(item.get("bidStart")),
                    "bidEnd": format_date(item.get("bidEnd")),
                    "minBid": item.get("minBid"),
                    "appraisal": item.get("appraisal"),
                    "org": item.get("org") or ann.get("org") or "",
                    "url": item_url(item),
                    "note": note,
                }
            )
    return rows


class OnbidClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01"}
        )

    def _csrf_headers(self, url: str) -> dict[str, str]:
        res = self.session.get(url, timeout=30)
        res.raise_for_status()
        csrf = re.search(r'name\s*=\s*"_csrf"\s+content\s*=\s*"([^"]+)"', res.text)
        if not csrf:
            raise RuntimeError("온비드 CSRF 토큰을 찾지 못했습니다.")
        return {
            "X-CSRF-TOKEN": csrf.group(1),
            "AJAX": "true",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": url,
            "Origin": ORIGIN,
        }

    def _post(self, headers: dict[str, str], path: str, data: dict[str, str]) -> dict[str, Any]:
        res = self.session.post(f"{ORIGIN}{path}", data=data, headers=headers, timeout=30)
        res.raise_for_status()
        return res.json()

    def search_unf(self, headers: dict[str, str], query: str) -> dict[str, Any]:
        return self._post(
            headers,
            "/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/srchUnf.do",
            {"swd": query, "srchDiv": "ALL", "pageIndex": "1", "pageSize": "50"},
        )

    def lookup_item(self, headers: dict[str, str], cltr_mng_no: str) -> dict[str, Any]:
        json_data = self._post(
            headers,
            "/op/cltrpbancinf/cltr/cltrcdtnsrch/CltrCdtnSrchController/inqRlcNo.do",
            {"srchCltrMnmtNo": cltr_mng_no},
        )
        return json_data.get("resultVo") or {}

    def fetch_items(self, headers: dict[str, str], onbid_pbanc_no: Any, pbct_no: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        total = 0
        while page <= 20:
            json_data = self._post(
                headers,
                "/op/cltrpbancinf/pbanc/pbancdtlinf/PbancDtlInqController/inqPbancDtlCltrInf.do",
                {
                    "onbidPbancNo": str(onbid_pbanc_no),
                    "pbctNo": str(pbct_no),
                    "pageIndex": str(page),
                    "pageUnit": "100",
                },
            )
            batch = json_data.get("cltrInfVO") or []
            total = (json_data.get("paginationInfo") or {}).get("totalRecordCount") or total
            rows.extend(batch)
            if not batch or len(rows) >= total:
                break
            page += 1
        return rows

    def fetch_schedule(self, headers: dict[str, str], onbid_pbanc_no: Any, pbct_no: Any) -> list[dict[str, Any]]:
        json_data = self._post(
            headers,
            "/op/cltrpbancinf/pbanc/pbancdtlinf/PbancDtlInqController/inqPbancDtlBidInf.do",
            {"onbidPbancNo": str(onbid_pbanc_no), "pbctNo": str(pbct_no), "pageIndex": "1"},
        )
        return (json_data.get("pbancDtlBidInfVO") or {}).get("pbancDtlBidTtdoPlcVO") or []


def _nsq(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _money(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return None


def _to_item(raw: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "pbancMngNo": raw.get("pbancMngNo") or meta.get("pbancMngNo"),
        "cltrMngNo": raw.get("cltrMngNo") or raw.get("scrnIndctCltrMngNo"),
        "name": raw.get("onbidCltrNm"),
        "status": raw.get("pbctCltrStatNm")
        or raw.get("remainTime")
        or raw.get("pbancPbctCltrStatNm")
        or raw.get("exctStatNm")
        or "",
        "bidStart": raw.get("pbctBegnDtm") or raw.get("pbctBgngDt"),
        "bidEnd": raw.get("pbctDdlnDt"),
        "openDt": raw.get("pbctExctDt"),
        "minBid": _money(raw.get("lowstBidPrc")),
        "appraisal": _money(raw.get("cltrApslEvlAvgAmt")),
        "firstBid": _money(raw.get("frstBidPrc")),
        "round": raw.get("pbctNsq"),
        "org": raw.get("regOrgNm") or meta.get("org"),
        "use": raw.get("ctgrNm") or raw.get("ctgrFullNm"),
        "propertyType": raw.get("scrnPrptDvsnNm") or raw.get("prptDvsnNm"),
        "region": raw.get("sidoSgkEmd") or raw.get("sggnm"),
        "onbidCltrno": raw.get("onbidCltrno"),
        "onbidPbancNo": raw.get("onbidPbancNo") or meta.get("onbidPbancNo"),
        "pbctNo": raw.get("pbctNo") or meta.get("pbctNo"),
        "pbctCdtnNo": raw.get("pbctCdtnNo"),
        "cltrScrnGrpCd": raw.get("cltrScrnGrpCd"),
        "cltrPrptDivCd": raw.get("cltrPrptDivCd"),
        "inqCnt": _money(raw.get("inqCnt")),
        "bldSqms": _money(raw.get("bldSqms")),
        "landSqms": _money(raw.get("landSqms")),
        "feeRate": raw.get("feeRate"),
    }


def _saved_item_numbers(alias_items: dict[str, Any] | None, query: str) -> list[str]:
    if not alias_items:
        return []
    value = alias_items.get(query)
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(number) for number in value if number]


def _with_item_lookup(
    client: OnbidClient,
    headers: dict[str, str],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        number = str(row.get("cltrMngNo") or row.get("scrnIndctCltrMngNo") or "").strip()
        if not number:
            enriched.append(row)
            continue
        try:
            detail = client.lookup_item(headers, number)
        except Exception:
            enriched.append(row)
            continue
        if not (detail.get("onbidCltrno") or detail.get("scrnIndctCltrMngNo") or detail.get("cltrMngNo")):
            enriched.append(row)
            continue
        merged = {**row, **{key: value for key, value in detail.items() if value not in (None, "")}}
        merged["cltrMngNo"] = detail.get("cltrMngNo") or detail.get("scrnIndctCltrMngNo") or number
        enriched.append(merged)
    return enriched


def _unique_latest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("cltrMngNo") or row.get("scrnIndctCltrMngNo") or row.get("onbidCltrno") or "")
        if not key:
            continue
        prev = by.get(key)
        if not prev or _nsq(row.get("pbctNsq")) > _nsq(prev.get("pbctNsq")):
            by[key] = row
    return list(by.values())


def empty_announcement(original: str, current: str, note: str | None = None) -> dict[str, Any]:
    return {
        "originalPbanc": original,
        "currentPbanc": current,
        "note": note,
        "found": False,
        "title": None,
        "org": None,
        "itemCount": 0,
        "rounds": [],
        "schedule": [],
        "items": [],
        "onbidUrl": None,
    }


def fetch_announcement(
    client: OnbidClient,
    headers: dict[str, str],
    original: str,
    query: str,
    note: str | None = None,
    alias_items: dict[str, str] | None = None,
) -> dict[str, Any]:
    rec = empty_announcement(original, query, note)
    vo = client.search_unf(headers, query)
    output = vo.get("unfSrchOtptVO") or vo
    rounds = output.get("pbancRsltSrchRslt") or output.get("pbancSrchRslt") or []
    latest = sorted(rounds, key=lambda r: _nsq(r.get("pbctNsq")), reverse=True)[0] if rounds else None

    if not latest:
        saved_numbers = _saved_item_numbers(alias_items if alias_items is not None else alias_items_for(), query)
        for alias_item in saved_numbers:
            item = client.lookup_item(headers, alias_item)
            if item.get("onbidPbancNo"):
                latest = {
                    "pbctNo": item.get("pbctNo"),
                    "onbidPbancNo": item.get("onbidPbancNo"),
                    "pbancMngNo": item.get("pbancMngNo"),
                    "onbidPbancNm": item.get("onbidCltrNm"),
                    "regOrgNm": item.get("regOrgNm"),
                    "pbctNsq": item.get("pbctNsq"),
                    "exctStatNm": item.get("pbctCltrStatNm"),
                    "pbctBgngDt": item.get("pbctBegnDtm"),
                    "pbctDdlnDt": item.get("pbctDdlnDt"),
                    "pbctExctDt": item.get("pbctExctDt"),
                }
                rounds = [latest]
                break

    if not latest:
        return rec

    rec.update(
        {
            "found": True,
            "currentPbanc": latest.get("pbancMngNo") or query,
            "title": latest.get("onbidPbancNm"),
            "org": latest.get("regOrgNm"),
            "onbidPbancNo": latest.get("onbidPbancNo"),
            "latestRound": latest.get("pbctNsq"),
            "latestStatus": latest.get("exctStatNm"),
            "bidStart": latest.get("pbctBgngDt"),
            "bidEnd": latest.get("pbctDdlnDt"),
            "openDt": latest.get("pbctExctDt"),
            "pbctNo": latest.get("pbctNo"),
            "onbidUrl": (
                f"{ORIGIN}/op/cltrpbancinf/pbanc/pbancdtlinf/PbancDtlInqController/mvmnPbancDtl.do"
                f"?onbidPbancNo={latest.get('onbidPbancNo')}&pbctNo={latest.get('pbctNo')}"
            ),
            "rounds": [
                {
                    "pbctNo": r.get("pbctNo"),
                    "pbctNsq": r.get("pbctNsq"),
                    "exctStatNm": r.get("exctStatNm"),
                    "pbctBgngDt": r.get("pbctBgngDt"),
                    "pbctDdlnDt": r.get("pbctDdlnDt"),
                    "pbctExctDt": r.get("pbctExctDt"),
                }
                for r in rounds
            ],
        }
    )
    raw_items = client.fetch_items(headers, latest.get("onbidPbancNo"), latest.get("pbctNo"))
    uniq = _with_item_lookup(client, headers, _unique_latest(raw_items))
    rec["itemCount"] = len(uniq)
    rec["items"] = [
        _to_item(
            row,
            {
                "pbancMngNo": rec["currentPbanc"],
                "org": rec["org"],
                "onbidPbancNo": rec["onbidPbancNo"],
                "pbctNo": rec["pbctNo"],
            },
        )
        for row in sorted(uniq, key=lambda z: str(z.get("cltrMngNo") or ""))
    ]
    rec["schedule"] = [
        {
            "pbctNsq": x.get("pbctNsq"),
            "pbctBgngDt": x.get("pbctBgngDt"),
            "pbctDdlnDt": x.get("pbctDdlnDt"),
            "opbxDt": x.get("opbxDt"),
            "exctStatNm": x.get("exctStatNm"),
            "bidMthodNm": x.get("bidMthodNm"),
            "pbancBidDivNm": x.get("pbancBidDivNm"),
        }
        for x in client.fetch_schedule(headers, latest.get("onbidPbancNo"), latest.get("pbctNo"))
    ]
    return rec


def refresh_tracked() -> dict[str, Any]:
    tracked = load_tracked()
    alias_items = alias_items_for(tracked)
    client = OnbidClient()
    headers = client._csrf_headers(
        f"{ORIGIN}/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do"
    )
    announcements = []
    for item in tracked:
        query = item.get("alias") or item["originalPbanc"]
        try:
            announcement = fetch_announcement(
                client,
                headers,
                item["originalPbanc"],
                query,
                item.get("note"),
                alias_items,
            )
            if announcement.get("found"):
                remember_item_numbers(item["originalPbanc"], announcement.get("items") or [])
            announcements.append(announcement)
        except Exception:
            announcements.append(empty_announcement(item["originalPbanc"], query, item.get("note")))
    data = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "source": ORIGIN,
        "announcementCount": len(announcements),
        "foundCount": sum(1 for a in announcements if a.get("found")),
        "missingCount": sum(1 for a in announcements if not a.get("found")),
        "itemCount": sum(len(a.get("items") or []) for a in announcements),
        "announcements": announcements,
    }
    save_snapshot(data)
    return data


def search_onbid(query: str) -> dict[str, Any]:
    q = query.strip()
    client = OnbidClient()
    headers = client._csrf_headers(
        f"{ORIGIN}/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do"
    )
    if re.fullmatch(r"\d{4}-\d{4}-\d{6}", q):
        item = client.lookup_item(headers, q)
        if item.get("onbidCltrno"):
            pbanc = item.get("pbancMngNo") or ""
            announcement = fetch_announcement(client, headers, pbanc, pbanc) if pbanc else None
            return {"query": q, "announcement": announcement, "cltrMngNo": q}
    return {"query": q, "announcement": fetch_announcement(client, headers, q, q)}
