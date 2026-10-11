#!/usr/bin/env python3
"""Stage the user-supplied Whistler Excel master without importing to PostgreSQL.

Usage:
  python imports/the_whistler/stage_master.py "path/to/the_whistler_master_episode_list(1).xlsx"
Produces CSVs under imports/the_whistler/staged/. This is read-only for PostgreSQL.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parent
EXPECTED={
 "Master Episodes":["Episode Number","Air Date","Title","Description","Repeat Of",
  "Broadcast Status","Original Author","Adapted By","Feature Type",
  "Source Work Title","Preservation Status","Primary Source"],
 "Schedule Interruptions":["Date","Classification","Explanation","Confidence"],
 "Source Discrepancies":["Date / Episode","Canonical / Working Value","Source(s)","Issue Type","Details"],
 "Source Coverage":["Source","Coverage / Use","URL","Notes"],
}
def value(v):
 if v is None:return ""
 if isinstance(v,(date,datetime)):return v.strftime("%Y-%m-%d")
 return str(v).strip()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("workbook",type=Path)
 p.add_argument("--output",type=Path,default=ROOT/"staged")
 a=p.parse_args()
 if not a.workbook.is_file():raise ValueError(f"Workbook not found: {a.workbook}")
 wb=load_workbook(a.workbook,read_only=True,data_only=True)
 staged={}
 for name,columns in EXPECTED.items():
  if name not in wb:raise ValueError(f"Missing sheet: {name}")
  iterator=wb[name].iter_rows(values_only=True)
  headers=[value(c) for c in next(iterator)]
  if headers != columns:raise ValueError(f"Unexpected columns in {name}: {headers}")
  rows=[dict(zip(headers,[value(v) for v in cells])) for cells in iterator
        if any(v is not None and str(v).strip() for v in cells)]
  staged[name]=rows
 episodes=staged["Master Episodes"]
 if len(episodes)!=692:raise ValueError(f"Expected 692 broadcast rows, received {len(episodes)}")
 numbers=[int(r["Episode Number"]) for r in episodes]
 if sorted(numbers)!=list(range(1,693)):raise ValueError("Episode numbers must be 1..692 exactly once")
 if len({r["Air Date"] for r in episodes})!=692:raise ValueError("Duplicate/missing broadcast dates")
 for row in episodes:
  if not row["Title"] or not row["Air Date"] or not row["Primary Source"]:
   raise ValueError(f"Missing required episode fields: {row['Episode Number']}")
  if row["Repeat Of"] and int(row["Repeat Of"]) not in numbers:
   raise ValueError(f"Unknown repeat candidate: {row['Episode Number']}")
 a.output.mkdir(parents=True,exist_ok=True)
 targets={
  "Master Episodes":"the_whistler_master_broadcasts.csv",
  "Schedule Interruptions":"the_whistler_schedule_interruptions.csv",
  "Source Discrepancies":"the_whistler_source_discrepancies.csv",
  "Source Coverage":"the_whistler_source_coverage.csv",
 }
 for sheet,filename in targets.items():
  with (a.output/filename).open("w",encoding="utf-8-sig",newline="") as f:
   writer=csv.DictWriter(f,fieldnames=EXPECTED[sheet]);writer.writeheader()
   writer.writerows(staged[sheet])
 repeat=sum(bool(r["Repeat Of"]) for r in episodes)
 statuses=Counter(r["Broadcast Status"] for r in episodes)
 print(f"Broadcasts: {len(episodes)}; candidate repeat/remake links: {repeat}")
 print("Broadcast statuses:",dict(statuses))
 print("Interruptions:",len(staged["Schedule Interruptions"]))
 print("Source discrepancies:",len(staged["Source Discrepancies"]))
 print("Source references:",len(staged["Source Coverage"]))
 print("Writer/adapter credits are blank in this workbook; no identities inferred.")
 print(f"Staged CSVs: {a.output}")
 print("No database modifications made.")
if __name__=="__main__":
 try:main()
 except (OSError,ValueError,KeyError) as exc:
  raise SystemExit(f"ERROR: {exc}")
