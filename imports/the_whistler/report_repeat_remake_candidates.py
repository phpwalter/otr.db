#!/usr/bin/env python3
"""Review The Whistler's provisional title-match references, without DB writes.

Inputs: staged master broadcasts and optional staged source discrepancies.
Output: CSV with source/ref evidence, side-by-side episode data and blank
review_decision/review_notes columns. No historical repeat/remake inference.
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT / "staged"

def load(path: Path) -> list[dict[str,str]]:
    with path.open("r",encoding="utf-8-sig",newline="") as file:
        return list(csv.DictReader(file))

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staged-dir",type=Path,default=DEFAULT)
    ap.add_argument("--output",type=Path,default=ROOT/"repeat_remake_review.csv")
    args=ap.parse_args()
    episodes=load(args.staged_dir/"the_whistler_master_broadcasts.csv")
    if len(episodes)!=692:raise ValueError(f"Expected 692 staged broadcasts; got {len(episodes)}")
    by_number={r["Episode Number"]:r for r in episodes}
    if len(by_number)!=692:raise ValueError("Duplicate episode numbers in source")
    candidates=[r for r in episodes if r.get("Repeat Of","").strip()]
    if len(candidates)!=117:raise ValueError(f"Expected 117 candidate links; got {len(candidates)}")
    discrepancies_path=args.staged_dir/"the_whistler_source_discrepancies.csv"
    discrepancies=load(discrepancies_path) if discrepancies_path.is_file() else []
    output=[]
    for row in candidates:
        target_number=row["Repeat Of"].strip()
        target=by_number.get(target_number)
        if not target:raise ValueError(f"Missing referenced episode #{target_number}")
        if int(target_number)>=int(row["Episode Number"]):
            raise ValueError(f"Reference is not earlier: #{row['Episode Number']} -> #{target_number}")
        # Compare structured discrepancy references, not substrings of prose.
        # Episode 32 must not match episode 532, nor dates mentioned only in details.
        def linked_discrepancy(d):
            identifier = d.get("Date / Episode", "")
            dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", identifier))
            numbers = set(re.findall(r"#(\d+)\b", identifier))
            return (row["Air Date"] in dates or target["Air Date"] in dates
                    or row["Episode Number"] in numbers or target_number in numbers)
        related = [d for d in discrepancies if linked_discrepancy(d)]
        unknown = (row["Title"].strip().casefold() == "title unknown" or
                   target["Title"].strip().casefold() == "title unknown")
        same_title = row["Title"].strip().casefold() == target["Title"].strip().casefold()
        priority = "unknown_title" if unknown else ("source_discrepancy" if related else "review")
        output.append({
            "candidate_episode_number":row["Episode Number"],
            "candidate_air_date":row["Air Date"],
            "candidate_title":row["Title"],
            "candidate_description":row.get("Description",""),
            "candidate_status":row["Broadcast Status"],
            "candidate_primary_source":row["Primary Source"],
            "candidate_preservation_status":row.get("Preservation Status",""),
            "referenced_episode_number":target_number,
            "referenced_air_date":target["Air Date"],
            "referenced_title":target["Title"],
            "referenced_description":target.get("Description",""),
            "referenced_status":target["Broadcast Status"],
            "referenced_primary_source":target["Primary Source"],
            "referenced_preservation_status":target.get("Preservation Status",""),
            "title_exact_match":str(same_title and not unknown),
            "title_unknown":str(unknown),
            "review_priority":priority,
            "source_discrepancies": " | ".join(f"{d.get('Date / Episode','')}: {d.get('Issue Type','')}: {d.get('Details','')}" for d in related),
            "review_decision":"",
            "review_evidence":"",
            "review_notes":"",
        })
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8-sig",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    counts=Counter(r["candidate_status"] for r in output)
    print(f"Review candidates: {len(output)}")
    print("Candidate statuses:",dict(counts))
    print(f"Informative exact title matches: {sum(r['title_exact_match']=='True' for r in output)}")
    print(f"Unknown-title placeholders: {sum(r['title_unknown']=='True' for r in output)}")
    print(f"Candidates with directly referenced discrepancies: {sum(bool(r['source_discrepancies']) for r in output)}")
    print("All review decisions are blank; none is automatically confirmed as a repeat or remake.")
    print(f"Review CSV: {args.output}")
    print("No database changes made.")

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        sys.exit(1)
