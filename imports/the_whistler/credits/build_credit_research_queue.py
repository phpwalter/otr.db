#!/usr/bin/env python3
"""Build a 692-episode source research queue for Whistler cast and writer credits.

No episode credits are asserted without a per-episode source. This queue tracks
where to look and what to transcribe. Separates episode evidence from series cast.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

HERE=Path(__file__).resolve().parent
MASTER=HERE.parent/"staged"/"the_whistler_master_broadcasts.csv"
SOURCES=[
 ("updated_whistler_log","https://sites.google.com/view/the-whistler-files/home",
  "Check latest log's episode comments and cast notes"),
 ("ucsb_george_allen_scripts","https://archives.library.ucsb.edu/repositories/2/resources/4629",
  "Locate script if held (1945-1954 subset); transcribe title-page author and cast"),
 ("archival_audio","https://archive.org/details/the-whistler-project?tab=collection",
  "Check surviving audio for spoken credits; identify recording variant and timestamp"),
]
FIELDS=("episode_number","air_date","title","source_key","source_url","research_instruction",
        "source_record_reference","credit_person","credit_type","character","evidence_quote",
        "audio_timestamp","verification_status","notes")
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master",type=Path,default=MASTER)
    ap.add_argument("--output",type=Path,default=HERE/"episode_credit_research_queue.csv")
    args=ap.parse_args()
    with args.master.open(encoding="utf-8-sig",newline="") as f:
        episodes=list(csv.DictReader(f))
    if len(episodes)!=692 or {int(e["Episode Number"]) for e in episodes}!=set(range(1,693)):
        raise ValueError("Master must contain exactly one of each episode 1..692")
    if args.output.resolve()==args.master.resolve():raise ValueError("Refusing to overwrite master")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
        for ep in episodes:
            for key,url,instruction in SOURCES:
                writer.writerow(dict(episode_number=ep["Episode Number"],
                    air_date=ep["Air Date"],title=ep["Title"],source_key=key,
                    source_url=url,research_instruction=instruction,
                    source_record_reference="",credit_person="",credit_type="",
                    character="",evidence_quote="",audio_timestamp="",
                    verification_status="not_researched",notes=""))
    print(f"Episodes: {len(episodes)}; research tasks: {len(episodes)*len(SOURCES)}")
    print(f"Research queue: {args.output}")
    print("No episode credit claims or database changes.")
if __name__=="__main__":main()
