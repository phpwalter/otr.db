#!/usr/bin/env python3
"""Harvest source-reported Whistler episode credits from Radio Index pages.

Fetches the series episode listing, follows only /series/the-whistler/episodes/
detail links, extracts page-local Cast & Crew fields, and requires exact
normalized title + date master match. No credits are production-verified;
never modifies PostgreSQL. Respect --limit and --delay when crawling.
"""
from __future__ import annotations
import argparse
import csv
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

HERE=Path(__file__).resolve().parent
INDEX="https://www.radioindex.org/series/the-whistler/episodes"
COLUMNS=["air_date","title","person_name","credit_type","source_url",
         "source_credit_label","verification_status"]
ROLE_MAP={"actor":"actor","writer":"writer","announcer":"announcer",
          "narrator":"narrator","musician":"musician","producer":"producer",
          "director":"director","adapter":"adapter"}
class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[];self.text=[];self.href=None
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if tag=="a":self.href=data.get("href")
        if tag in {"h1","h2","h3","p","li","div","section","br"}:
            self.text.append("\n")
    def handle_endtag(self,tag):
        if tag=="a":self.href=None
        if tag in {"h1","h2","h3","p","li","div","section"}:self.text.append("\n")
    def handle_data(self,data):
        value=data.strip()
        if not value:return
        if self.href:self.links.append((self.href,value))
        self.text.append(value+"\n")
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"OTR historical credits research (+manual source review)"})
    with urllib.request.urlopen(req,timeout=25) as resp:
        if resp.status!=200:raise ValueError(f"HTTP {resp.status}")
        return resp.read(3_000_000).decode("utf-8","replace")
def norm(s):
    return re.sub(r"[^a-z0-9]+","",s.casefold())
def links_for_index(text):
    parser=Page();parser.feed(text)
    urls=[]
    for href,_ in parser.links:
        url=urllib.parse.urljoin(INDEX,href).split("#")[0].split("?")[0].rstrip("/")
        parts=urllib.parse.urlparse(url)
        if parts.netloc!="www.radioindex.org" or not parts.path.startswith("/series/the-whistler/episodes/"):
            continue
        if url not in urls:urls.append(url)
    return urls
def extract(url,source,master):
    page=Page();page.feed(source)
    lines=[s.strip() for s in "".join(page.text).splitlines() if s.strip()]
    # Restrict to the actual per-episode Cast & Crew section; discard unrelated
    # navigation cards and recommended-episode contributor text.
    start=next((i for i,s in enumerate(lines) if s.casefold()=="cast & crew"),None)
    if start is None:return [],"no_cast_crew_section"
    stop=next((i for i in range(start+1,len(lines)) if lines[i].casefold() in ("details","related episodes","more episodes")),len(lines))
    section=lines[start+1:stop]
    # Input from HTML parser may have name/role on separate lines or same line.
    observations=[]
    for i,line in enumerate(section):
        # Page DOM often places person on one line, occupation on the next.
        # An occupation label must be present; do not guess a credit from the name.
        for role in ROLE_MAP:
            pattern=r"^(.*?)\s*(Actor|Writer|Announcer|Narrator|Musician|Producer|Director|Adapter)(?:\s*/\s*(?:Narrator|Producer|Director))?$"
            m=re.match(pattern,line,re.I)
            if m and m.group(1).strip():
                observations.append((m.group(1).strip(),m.group(2).lower()))
                break
            if line.casefold()==role and i>0:
                observations.append((section[i-1],role))
                break
    # Never assume an extracted cast name is correctly associated until the
    # page's date/title independently selects exactly one master broadcast.
    candidate_title=next((x for x in lines if norm(x)==norm(master[0]["Title"])),None) if len(master)==1 else None
    return observations,"extracted" if observations else "unparsed_cast_crew"
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--master",type=Path,default=HERE.parent/"staged"/"the_whistler_master_broadcasts.csv")
    ap.add_argument("--output",type=Path,default=HERE/"radioindex_crawl_observations.csv")
    ap.add_argument("--exceptions",type=Path,default=HERE/"radioindex_crawl_exceptions.csv")
    ap.add_argument("--limit",type=int,default=25)
    ap.add_argument("--delay",type=float,default=1.0)
    args=ap.parse_args()
    if args.limit<1 or args.delay<0.5:raise ValueError("Use positive --limit and --delay >=0.5")
    with args.master.open(encoding="utf-8-sig",newline="") as f:master=list(csv.DictReader(f))
    if len(master)!=692:raise ValueError("Expected 692 master rows")
    by_title=defaultdict(list)
    for r in master:by_title[norm(r["Title"])].append(r)
    urls=links_for_index(get(INDEX))
    if not urls:raise ValueError("No episode links found; index layout may have changed")
    observations=[];exceptions=[]
    for url in urls[:args.limit]:
        time.sleep(args.delay)
        try:
            raw=get(url);page=Page();page.feed(raw)
            lines=[x.strip() for x in "".join(page.text).splitlines() if x.strip()]
            heading=next((x for x in lines if x.casefold() not in ("the whistler","radioindex.org") and
                           norm(x)==norm(url.rsplit("/",1)[-1].replace("-"," "))),None)
            dates=re.findall(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Z][a-z]+ \d{1,2}, 19\d{2})", " ".join(lines))
            from datetime import datetime
            date=datetime.strptime(dates[0],"%B %d, %Y").date().isoformat() if dates else ""
            candidates=[r for r in master if r["Air Date"]==date and
                (norm(r["Title"])==norm(heading or "") or norm(r["Title"])==norm(url.rsplit("/",1)[-1].replace("-"," ")))]
            if len(candidates)!=1:
                exceptions.append((url,"unmatched_date_title",date,heading or ""))
                continue
            credits,status=extract(url,raw,candidates)
            if not credits:exceptions.append((url,status,date,candidates[0]["Title"]));continue
            for name,role in credits:
                observations.append(dict(air_date=date,title=candidates[0]["Title"],person_name=name,
                    credit_type=role,source_url=url,source_credit_label=role,
                    verification_status="source_reported"))
        except (urllib.error.URLError,ValueError) as ex:
            exceptions.append((url,"fetch_or_parse_error","",str(ex)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader();w.writerows(observations)
    with args.exceptions.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(["source_url","reason","air_date","detail"]);w.writerows(exceptions)
    print(f"Index detail links: {len(urls)}; inspected: {min(args.limit,len(urls))}")
    print(f"Source-reported observations: {len(observations)}; exceptions: {len(exceptions)}")
    print("Output:",args.output)
    print("No episode_verified promotions or database writes.")
if __name__=="__main__":main()
