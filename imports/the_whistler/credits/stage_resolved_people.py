#!/usr/bin/env python3
"""Safely stage manually resolved Whistler contributors; never writes PostgreSQL.

Input comes from reconcile_people.py. Reviewers set resolved_person_id and
identity_evidence for reuse, or identity_review_status='create_new_reviewed'
with identity_evidence for new persons. Source names alone cannot imply identity.
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,default=HERE/"person_identity_review.csv")
    p.add_argument("--output-dir",type=Path,default=HERE/"staged")
    a=p.parse_args()
    with a.input.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        required={"person_name","series_role","source_url","resolved_person_id","identity_evidence","identity_review_status"}
        if not required.issubset(reader.fieldnames or []):raise ValueError("Missing review columns")
        rows=list(reader)
    if not rows:raise ValueError("Empty identity review")
    seen=set();reused=[];new=[];pending=[]
    for r in rows:
        name=r["person_name"].strip()
        if not name or name.casefold() in seen:raise ValueError("Blank or duplicate person")
        seen.add(name.casefold())
        evidence=r["identity_evidence"].strip()
        person_id=r["resolved_person_id"].strip()
        state=r["identity_review_status"].strip()
        if person_id and person_id.isdecimal() and int(person_id)>0 and evidence:
            chosen=set(filter(None,r.get("matching_person_ids","").split(";")))
            if person_id not in chosen:
                raise ValueError(f"{name}: resolved ID not among exact-match candidates; needs separate verification")
            reused.append(r)
        elif state=="create_new_reviewed" and not person_id and evidence and r["source_url"].startswith(("https://","http://")):
            new.append(r)
        else:
            pending.append(r)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    columns=list(rows[0])
    for filename,data in (("people_reuse_reviewed.csv",reused),("people_new_reviewed.csv",new),("people_pending_review.csv",pending)):
        with (a.output_dir/filename).open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=columns)
            w.writeheader();w.writerows(data)
    print(f"Total: {len(rows)}; reviewed reuse: {len(reused)}; reviewed new: {len(new)}; pending: {len(pending)}")
    print("No person records or episode credits written.")
if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError) as e:
        print(f"ERROR: {e}",file=sys.stderr)
        sys.exit(1)
