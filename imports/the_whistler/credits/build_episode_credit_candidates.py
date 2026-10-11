#!/usr/bin/env python3
"""Convert source-transcribed Whistler credit research into episode-credit intake.

Only rows marked episode_verified, with named person and attributable evidence,
are eligible. Deduplicates (episode, person, type, character), writes exception
report. Never modifies PostgreSQL or makes unverified credit assertions.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

HERE=Path(__file__).resolve().parent
FIELDS=("episode_number","air_date","episode_title","person_name","credit_type",
        "character","billing_order","source_url","source_excerpt","verification_status")
VALID={"actor","writer","narrator","adapter"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue",type=Path,default=HERE/"episode_credit_research_queue.csv")
    p.add_argument("--output",type=Path,default=HERE/"episode_credit_candidates.csv")
    p.add_argument("--exceptions",type=Path,default=HERE/"episode_credit_research_exceptions.csv")
    a=p.parse_args()
    if len({x.resolve() for x in (a.queue,a.output,a.exceptions)})!=3:
        raise ValueError("Input and outputs must be separate")
    with a.queue.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    expected={"episode_number","air_date","title","credit_person","credit_type",
              "character","source_url","evidence_quote","verification_status"}
    if not rows or not expected.issubset(rows[0]):raise ValueError("Research queue missing required columns")
    eligible=[];exceptions=[];seen=set()
    for r in rows:
        if r["verification_status"]=="not_researched" and not r["credit_person"].strip():
            continue
        reasons=[]
        if r["verification_status"]!="episode_verified":reasons.append("not_episode_verified")
        if not r["credit_person"].strip():reasons.append("missing_person")
        if r["credit_type"] not in VALID:reasons.append("invalid_credit_type")
        if not r["source_url"].startswith(("https://","http://")):reasons.append("missing_source")
        if not r["evidence_quote"].strip():reasons.append("missing_evidence_excerpt")
        key=(r["episode_number"],r["credit_person"].strip().casefold(),r["credit_type"],r["character"].strip().casefold())
        if key in seen:reasons.append("duplicate_credit")
        if reasons:
            exceptions.append({**r,"exception_reasons":";".join(reasons)})
            continue
        seen.add(key)
        eligible.append(dict(episode_number=r["episode_number"],air_date=r["air_date"],
            episode_title=r["title"],person_name=r["credit_person"].strip(),
            credit_type=r["credit_type"],character=r["character"],
            billing_order="",source_url=r["source_url"],
            source_excerpt=r["evidence_quote"],verification_status="episode_verified"))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(eligible)
    if exceptions:
        with a.exceptions.open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(exceptions[0]))
            writer.writeheader();writer.writerows(exceptions)
    elif a.exceptions.exists():
        a.exceptions.unlink()
    print(f"Research rows: {len(rows)}; evidence-backed credits: {len(eligible)}; exceptions: {len(exceptions)}")
    print("Next: python imports/the_whistler/credits/validate_episode_credits.py")
    print("No database changes.")
if __name__=="__main__":main()
