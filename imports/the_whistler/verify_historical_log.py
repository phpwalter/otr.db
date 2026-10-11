#!/usr/bin/env python3
"""Cross-check Whistler's first 20 candidates against Haendiges' published log.

Read-only to PostgreSQL. Fetches a historical catalog, compares numbered/date/title
rows, and writes source-specific findings to a NEW CSV. Catalog presence/availability
is NEVER interpreted as proof of identical recordings or a remake.
"""
from __future__ import annotations
import argparse
import csv
import html
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
URL="https://otrsite.com/logs/logw1002.htm"
FIRST={51,72,80,93,215,222,253,254,259,291,292,307,308,315,350,359,361,362,375,377}
# Haendiges lists multiple sections, including separately numbered East Coast shows.
# Only accept rows with number/date AND title; detect ambiguous matching explicitly.
ROW=re.compile(r'^\s*(?P<catalog>\*na\*|\d{5}[A-Z]?)\s+"(?P<title>[^"]+)"\s+(?P<number>\d{1,3})\s+(?P<date>\d{2}-\d{2}-\d{2})(?:\s|$)',re.I)

def norm(s: str)->str:
    return re.sub(r"[^a-z0-9]+","",html.unescape(s).casefold())

def fetch(url: str)->str:
    req=urllib.request.Request(url,headers={"User-Agent":"OTR-Catalog-Research/1.0"})
    with urllib.request.urlopen(req,timeout=30) as response:
        raw=response.read(2_000_000)
    # Log is monospaced/preformatted. Preserve newline and horizontal whitespace.
    text=html.unescape(raw.decode("utf-8","replace"))
    text=re.sub(r"<br\s*/?>","\n",text,flags=re.I)
    text=re.sub(r"<[^>]+>","",text)
    return text.replace("\u00a0"," ")

def parse_log(text: str)->dict[tuple[int,str],list[dict[str,str]]]:
    result={}
    for line in text.splitlines():
        m=ROW.match(line)
        if not m:continue
        date=datetime.strptime(m["date"],"%m-%d-%y").date()
        # The historical log covers 1942..1955, not 2042..2055.
        date=date.replace(year=date.year-100) if date.year>=2000 else date
        key=(int(m["number"]),date.isoformat())
        result.setdefault(key,[]).append(m.groupdict())
    return result

def lookup(log,episode,date,title):
    matches=log.get((int(episode),date),[])
    same=[x for x in matches if norm(x["title"])==norm(title)]
    if len(same)==1:
        x=same[0]
        return "matched",x["catalog"],x["title"],""
    if len(same)>1:return "ambiguous","","","Multiple matching numbered/date/title entries"
    if matches:return "title_conflict","","","Log has numbered/date row with different title: "+ "; ".join(x["title"] for x in matches)
    return "not_found","","","No matching numbered/date row located in fetched log"

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",type=Path,default=HERE/"repeat_remake_evidence_review.csv")
    ap.add_argument("--output",type=Path,default=HERE/"repeat_remake_historical_log_audit.csv")
    ap.add_argument("--log-file",type=Path,help="Optional local HTML/text log snapshot; avoids network")
    args=ap.parse_args()
    if args.input.resolve()==args.output.resolve():raise ValueError("Input and output must differ")
    with args.input.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        fields=reader.fieldnames or []
        rows=list(reader)
    if len(rows)!=117:raise ValueError("Expected 117 reconciled records")
    if len({r["candidate_episode_number"] for r in rows})!=117:
        raise ValueError("Duplicate candidate episode numbers")
    if not FIRST.issubset({int(r["candidate_episode_number"]) for r in rows}):
        raise ValueError("First-batch episode list differs from expected")
    log=parse_log(args.log_file.read_text(encoding="utf-8-sig") if args.log_file else fetch(URL))
    if len(log)<400:raise ValueError(f"Parsed only {len(log)} log keys; source layout may have changed")
    newfields=("log_candidate_status","log_candidate_catalog","log_candidate_title",
               "log_referenced_status","log_referenced_catalog","log_referenced_title",
               "log_notes","log_source","log_verification")
    count=0
    for row in rows:
        if int(row["candidate_episode_number"]) not in FIRST:continue
        ca=lookup(log,row["candidate_episode_number"],row["candidate_air_date"],row["candidate_title"])
        ref=lookup(log,row["referenced_episode_number"],row["referenced_air_date"],row["referenced_title"])
        row.update(zip(newfields,(
            ca[0],ca[1],ca[2],ref[0],ref[1],ref[2],
            " | ".join(x for x in (ca[3],ref[3]) if x),
            URL,"catalog_only_no_production_verification")))
        # The source contains availability codes, not reliable production identities.
        # Do not overwrite any user-provided decisions, evidence, or notes.
        count+=1
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields+[k for k in newfields if k not in fields])
        writer.writeheader()
        writer.writerows(rows)
    validated=sum(1 for r in rows if r.get("log_candidate_status")=="matched" and
                  r.get("log_referenced_status")=="matched")
    print(f"Log rows parsed: {len(log)}")
    print(f"First-batch candidates checked: {count}")
    print(f"Pairs matching both dated catalog entries: {validated}/{count}")
    print(f"Audit: {args.output}")
    print("No repeat/remake confirmed; no PostgreSQL updates.")

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError,urllib.error.URLError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
