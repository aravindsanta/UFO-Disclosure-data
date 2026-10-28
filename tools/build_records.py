#!/usr/bin/env python3
"""Build data/records.json from AARO's official DVIDS uploads.

AARO (All-domain Anomaly Resolution Office, DVIDS unit 8597) posts every
PURSUE video release to DVIDS. This script lists all of AARO's assets,
fetches each one's details, and writes the index the iOS app downloads.

API key: DVIDS_API_KEY env var, else ~/.config/ufo/dvids_key.
Usage:   python3 tools/build_records.py [--out data/records.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.dvidshub.net"
AARO_UNIT_ID = "8597"
PREFERRED_WIDTH = 1280  # 720p: sharp on phones at ~1/3 the size of 1080p

# DVIDS keyword tag -> official PURSUE release tranche
TRANCHE_TAGS = {
    "AAR052226": "Release 02",
    "AARO061226": "Release 03",
    "AARO071026": "Release 04",
    "AARO080726": "Release 05",
    "AARO091826": "Release 06",
}
RELEASE_01_DATES = {"2026-05-07", "2026-05-08"}  # launch tranche carried no tag

AGENCY_BY_PREFIX = {
    "DOW": "Department of War",
    "FBI": "Federal Bureau of Investigation",
    "NASA": "NASA",
    "LLE": "Local Law Enforcement",
}

ID_PATTERN = re.compile(r"^((?:[A-Z]+-UAP-)?(?:PR|D)-?\d+[a-z]?)[,_ ]\s*", re.IGNORECASE)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
YEAR_PATTERN = re.compile(rf"^(?:(?:{MONTHS}) )?(?:\d{{1,2}}/\d{{1,2}}/)?(\d{{4}})$")
TRAILING_YEAR = re.compile(r"^(.*?)\s+(\d{4})$")


def api_key() -> str:
    key = os.environ.get("DVIDS_API_KEY", "").strip()
    if not key:
        path = Path.home() / ".config/ufo/dvids_key"
        if path.exists():
            key = path.read_text().strip()
    if not key:
        sys.exit("DVIDS_API_KEY not set and ~/.config/ufo/dvids_key missing")
    return key


def get(endpoint: str, key: str, **params) -> dict:
    query = urllib.parse.urlencode({"api_key": key, **params})
    req = urllib.request.Request(f"{API}/{endpoint}?{query}", headers={"User-Agent": "UFODisclosure-indexer/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            if "errors" in data:
                raise RuntimeError(f"DVIDS error: {data['errors']}")
            return data
        except (OSError, json.JSONDecodeError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def list_aaro_assets(key: str) -> list[dict]:
    """DVIDS pagination is unstable (pages occasionally repeat one item and
    drop another), so union several sort orders until every asset is seen."""
    seen: dict[str, dict] = {}
    total = None
    for sort in ("publishdate", "date", "timestamp", "publishdate", "date"):
        page = 1
        while True:
            data = get("search", key, unit_id=AARO_UNIT_ID, max_results=50, page=page, sort=sort, sortdir="desc")
            total = data["page_info"]["total_results"]
            batch = data.get("results", [])
            seen.update((item["id"], item) for item in batch)
            if len(batch) < 50:
                break
            page += 1
        if len(seen) >= total:
            return list(seen.values())
    sys.exit(f"DVIDS listed {total} AARO assets but only {len(seen)} could be paged; not writing a partial index")


def pick_file(files: list[dict]) -> dict | None:
    mp4s = [f for f in files if f.get("type") == "video/mp4" and f.get("src")]
    if not mp4s:
        return None
    fitting = [f for f in mp4s if (f.get("width") or 0) <= PREFERRED_WIDTH]
    if fitting:
        return max(fitting, key=lambda f: (f.get("width") or 0, f.get("size") or 0))
    return min(mp4s, key=lambda f: f.get("width") or 0)


def tranche_for(asset: dict) -> str:
    for tag in (k.strip() for k in (asset.get("keywords") or "").split(",")):
        if tag in TRANCHE_TAGS:
            return TRANCHE_TAGS[tag]
    if asset["date_published"][:10] in RELEASE_01_DATES:
        return "Release 01"
    return "AARO Case Archive"


def split_title(raw: str) -> tuple[str, str, str]:
    """'DOW-UAP-PR149, Unresolved UAP Report, Middle East, 2023' ->
    ('DOW-UAP-PR149', 'Unresolved UAP Report', 'Middle East')."""
    raw = raw.strip()
    m = ID_PATTERN.match(raw)
    record_id = m.group(1).upper() if m else ""
    rest = raw[m.end():] if m else raw
    parts = [p.strip().strip("“”\"").strip() for p in rest.replace("_", ", ").split(",") if p.strip()]
    location = ""
    if parts and YEAR_PATTERN.match(parts[-1]):
        parts = parts[:-1]
        if len(parts) >= 2:
            location = parts.pop()
    elif parts and (m2 := TRAILING_YEAR.match(parts[-1])) and len(parts) >= 2:
        location = m2.group(1)  # 'Europe 2022'
        parts = parts[:-1]
    title = ", ".join(parts) or rest or raw
    return record_id, title, location


def incident_date(asset: dict) -> str:
    date = asset.get("date", "")[:10]
    # DVIDS stores year-only incidents as January 1 and month-only as the 1st
    if date.endswith("-01-01"):
        return date[:4]
    return date[:7] if date.endswith("-01") else date


def to_record(asset: dict) -> dict | None:
    chosen = pick_file(asset.get("files") or [])
    if not chosen:
        return None
    record_id, title, location = split_title(asset["title"])
    dvids_num = asset["id"].split(":")[-1]
    prefix = record_id.split("-")[0] if "-UAP-" in record_id else ""
    loc = asset.get("location") or {}
    if not location:
        location = ", ".join(x for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x) or "Undisclosed"
    is_audio = "audio" in asset["title"].lower()
    return {
        "id": record_id or f"DVIDS-{dvids_num}",
        "title": title,
        "agency": AGENCY_BY_PREFIX.get(prefix, "All-domain Anomaly Resolution Office"),
        "releaseTranche": tranche_for(asset),
        "releaseDate": asset["date_published"][:10],
        "incidentDate": incident_date(asset),
        "location": location,
        "fileType": "aud" if is_audio else "vid",
        "fileURL": chosen["src"],
        "fileSizeMB": round((chosen.get("size") or 0) / 1_000_000, 1),
        "summary": (asset.get("description") or "").strip(),
        "sourcePageURL": asset.get("url"),
        "thumbnailURL": asset.get("image") or (asset.get("thumbnail") or {}).get("url"),
        "durationSeconds": asset.get("duration"),
        "credit": f"{asset.get('unit_name', 'AARO')} / DVIDS",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data/records.json"))
    args = parser.parse_args()
    key = api_key()

    listed = list_aaro_assets(key)
    print(f"DVIDS lists {len(listed)} AARO assets", file=sys.stderr)
    records, skipped = [], []
    for item in listed:
        asset = get("asset", key, id=item["id"])["results"]
        record = to_record(asset)
        (records.append(record) if record else skipped.append(item["id"]))
        time.sleep(0.2)

    records.sort(key=lambda r: (r["releaseDate"], r["id"]), reverse=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Only rewrite when content changes, so scheduled runs don't churn commits
    payload = {"source": "DVIDS / All-domain Anomaly Resolution Office", "records": records}
    if out.exists():
        old = json.loads(out.read_text())
        if {k: v for k, v in old.items() if k != "generatedAt"} == payload:
            print("records.json unchanged", file=sys.stderr)
            return
    payload = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **payload}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records to {out}; skipped (no mp4): {skipped}", file=sys.stderr)


if __name__ == "__main__":
    main()
