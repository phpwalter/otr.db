#!/usr/bin/env python3
"""Transactional Whistler enrichment: reviewed people and episode credits.

Defaults to --dry-run (transaction ROLLBACK). No automatic approvals.
Person decisions CSV columns: name,action,person_id,evidence.
Actions: hold (default), existing (requires person_id), create (requires evidence).
Credit approval is a separate approved=yes flag in credit_candidates.csv.
Only catalog entries classified 'exact' can be imported.
"""
from __future__ import annotations
import argparse,csv,json,os,subprocess,sys
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"imports"/"the_whistler"))
from import_the_whistler import read_env,quote

ALLOWED={"yes","true","1"}
ROLES={"actor","writer","adapter","director","producer","announcer",
       "narrator","host","composer","sound_effects"}
SOURCE_TITLE="Whistler 556-entry user-supplied CBS catalog extract"

def csv_rows(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        rows=list(reader)
    for n,row in enumerate(rows,2):
        if None in row: raise ValueError(f"{path.name}: excess columns at row {n}")
        if any(v is None for k,v in row.items() if k!="approved"):
            raise ValueError(f"{path.name}: missing column value at row {n}")
        if "approved" in row and row["approved"] is None: row["approved"]=""
    return rows

def payload(args):
    catalog=csv_rows(args.catalog)
    credits=csv_rows(args.credits)
    eligible={r["catalog_id"]:r for r in catalog if r["status"]=="exact"}
    source={r["catalog_id"]:r for r in catalog}
    decisions={}
    if args.people.exists():
        for r in csv_rows(args.people):
            name=r["name"].strip()
            if not name or name in decisions:
                raise ValueError(f"Duplicate/empty person decision: {name!r}")
            action=r["action"].strip().lower() or "hold"
            if action not in ("hold","existing","create"):
                raise ValueError(f"Bad person action: {name}: {action}")
            if action!="hold" and not r["evidence"].strip():
                raise ValueError(f"Decision requires evidence: {name}")
            if action=="existing" and not r["person_id"].isdigit():
                raise ValueError(f"Existing decision requires person_id: {name}")
            if action=="create" and r["person_id"].strip():
                raise ValueError(f"New person must not have a person_id: {name}")
            decisions[name]=r
    approved=[r for r in credits if r["approved"].strip().lower() in ALLOWED]
    staged=[]
    for r in approved:
        catalog_id=r["catalog_id"]
        if catalog_id not in source:
            raise ValueError(f"Unknown catalog ID {catalog_id}")
        if catalog_id not in eligible:
            raise ValueError(f"Approved credit has non-exact episode match: {catalog_id}")
        if r["role"] not in ROLES:
            raise ValueError(f"Unsupported role for catalog {catalog_id}: {r['role']}")
        if not r["episode_id"].isdigit() or not r["person"].strip():
            raise ValueError(f"Missing episode ID/person: catalog {catalog_id}")
        c=eligible[catalog_id]
        if c["episode_id"]!=r["episode_id"] or c["date"]!=r["episode_date"]:
            raise ValueError(f"Credit identity disagrees with catalog: {catalog_id}")
        person_id=r["person_id"].strip()
        action="existing" if person_id.isdigit() else ""
        if not action:
            decision=decisions.get(r["person"].strip())
            if decision is None or decision["action"].strip().lower() not in ("existing","create"):
                raise ValueError(f"Unresolved identity: {r['person']}")
            action=decision["action"].strip().lower()
            person_id=decision["person_id"].strip()
        if person_id and not person_id.isdigit():
            raise ValueError(f"Invalid person_id: {r['person']}")
        if action=="create" and not decisions[r["person"].strip()]["evidence"].strip():
            raise ValueError(f"No person evidence: {r['person']}")
        staged.append(dict(catalog_id=catalog_id,episode_id=int(r["episode_id"]),
            date=r["episode_date"],title=r["episode_title"],person=r["person"].strip(),
            person_id=int(person_id) if person_id else None,action=action,role=r["role"]))
    identities={}
    for r in staged:
        n=r["person"].casefold()
        v=(r["action"],r["person_id"])
        if n in identities and identities[n]!=v:
            raise ValueError(f"Conflicting approved identity assignments: {r['person']}")
        identities[n]=v
    return staged,len(approved)

SQL=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.whistler.enrichment.v1'));
CREATE TEMP TABLE wh_in AS
 SELECT * FROM jsonb_to_recordset(__PAYLOAD__::jsonb) AS x(
 catalog_id text,episode_id bigint,air_date date,title text,
 person text,person_id bigint,action text,role text);
DO $validate$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.series WHERE slug='the-whistler')
 THEN RAISE EXCEPTION 'Whistler series slug not found'; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='otr_title_match_key')
 THEN RAISE EXCEPTION 'Title normalization function missing'; END IF;
 IF EXISTS (
 SELECT 1 FROM wh_in i LEFT JOIN public.episode e ON e.episode_id=i.episode_id
 LEFT JOIN public.series s ON s.series_id=e.series_id
 WHERE e.episode_id IS NULL OR s.slug IS DISTINCT FROM 'the-whistler'
 OR e.air_date IS DISTINCT FROM i.air_date
 OR public.otr_title_match_key(e.title) IS DISTINCT FROM public.otr_title_match_key(i.title)
 ) THEN RAISE EXCEPTION 'Episode/date/title/series validation failed'; END IF;
 IF EXISTS (SELECT 1 FROM wh_in i LEFT JOIN public.credit_type ct
 ON ct.credit_type=i.role WHERE ct.credit_type IS NULL)
 THEN RAISE EXCEPTION 'Unsupported credit role'; END IF;
 IF EXISTS (SELECT 1 FROM wh_in i LEFT JOIN public.person p ON p.person_id=i.person_id
 WHERE i.action='existing' AND (
 p.person_id IS NULL OR lower(trim(p.display_name)) <> lower(trim(i.person))))
 THEN RAISE EXCEPTION 'Existing contributor ID/name mismatch'; END IF;
 IF EXISTS (SELECT 1 FROM wh_in WHERE action NOT IN ('existing','create'))
 THEN RAISE EXCEPTION 'Invalid person action'; END IF;
 IF EXISTS (SELECT 1 FROM wh_in i
 WHERE i.action='create' AND EXISTS (
 SELECT 1 FROM public.person p WHERE lower(trim(p.display_name))=lower(trim(i.person))))
 THEN RAISE EXCEPTION 'Potential duplicate new person'; END IF;
END $validate$;
CREATE TEMP TABLE wh_new_names AS
 SELECT DISTINCT person FROM wh_in WHERE action='create';
INSERT INTO public.person(display_name,legacy_system)
 SELECT person,'WHISTLER_ENRICHMENT'
 FROM wh_new_names
 ORDER BY person;
CREATE TEMP TABLE wh_resolved AS
 SELECT i.*,COALESCE(i.person_id,p.person_id) AS resolved_person_id
 FROM wh_in i LEFT JOIN public.person p
 ON i.action='create' AND p.legacy_system='WHISTLER_ENRICHMENT'
 AND p.display_name=i.person;
DO $check$
BEGIN
 IF EXISTS(SELECT 1 FROM wh_resolved WHERE resolved_person_id IS NULL)
 THEN RAISE EXCEPTION 'Person identity resolution failed'; END IF;
END $check$;
INSERT INTO public.episode_credit(episode_id,person_id,credit_type,billing_order,notes)
SELECT r.episode_id,r.resolved_person_id,r.role,NULL,
 'Reviewed Whistler catalog credit; source catalog IDs: ' ||
 string_agg(DISTINCT r.catalog_id,', ' ORDER BY r.catalog_id)
FROM wh_resolved r
WHERE NOT EXISTS (
 SELECT 1 FROM public.episode_credit ec
 WHERE ec.episode_id=r.episode_id
 AND ec.person_id=r.resolved_person_id
 AND ec.credit_type=r.role)
GROUP BY r.episode_id,r.resolved_person_id,r.role
ON CONFLICT DO NOTHING;
INSERT INTO public.source(source_type,title,citation,notes)
SELECT 'catalog',__SOURCE__,
 'User-provided catalog; manually reviewed CBS episode credits',
 'No AFRS/syndication or archival attributes imported'
WHERE NOT EXISTS(SELECT 1 FROM public.source WHERE title=__SOURCE__);
INSERT INTO public.entity_source(source_id,entity_type,entity_id,source_role,confidence,notes)
SELECT s.source_id,'episode_credit',ec.episode_credit_id,
 'catalog_observation','medium',
 'Reviewed catalog IDs: '||string_agg(DISTINCT i.catalog_id,', ' ORDER BY i.catalog_id)
FROM wh_resolved i
JOIN public.episode_credit ec ON ec.episode_id=i.episode_id
 AND ec.person_id=i.resolved_person_id AND ec.credit_type=i.role
JOIN public.source s ON s.title=__SOURCE__
GROUP BY s.source_id,ec.episode_credit_id
ON CONFLICT (source_id,entity_type,entity_id,source_role) DO NOTHING;
SELECT (SELECT count(*) FROM wh_in) AS approved_claims,
 (SELECT count(*) FROM wh_new_names) AS new_person_names,
 (SELECT count(DISTINCT (episode_id,resolved_person_id,role)) FROM wh_resolved)
 AS distinct_credit_keys;
__END__;
"""

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog",type=Path,default=HERE/"catalog_reconciliation.csv")
    p.add_argument("--credits",type=Path,default=HERE/"credit_candidates.csv")
    p.add_argument("--people",type=Path,default=HERE/"reports"/"person_decisions.csv")
    p.add_argument("--env",type=Path,default=ROOT/".env")
    mode=p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run",action="store_true")
    mode.add_argument("--apply",action="store_true")
    a=p.parse_args()
    entries,total=payload(a)
    print(f"Mode: {'APPLY' if a.apply else 'DRY RUN'}",flush=True)
    print(f"Approved source claims: {total}; staged: {len(entries)}",flush=True)
    if not entries:
        print("Nothing approved. No database changes; review source credits and person decisions.")
        return 0
    cfg=read_env(a.env)
    env=os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],
        PGDATABASE=cfg["DB_NAME"],PGUSER=cfg["DB_USER"],
        PGPASSWORD=cfg["DB_PASSWORD"],PGSSLMODE=cfg.get("DB_SSLMODE","prefer"),
        PGCLIENTENCODING="UTF8")
    input_rows=[dict(catalog_id=r["catalog_id"],episode_id=r["episode_id"],
        air_date=r["date"],title=r["title"],person=r["person"],
        person_id=r["person_id"],action=r["action"],role=r["role"]) for r in entries]
    sql=SQL.replace("__PAYLOAD__",quote(json.dumps(input_rows,ensure_ascii=False)))
    sql=sql.replace("__SOURCE__",quote(SOURCE_TITLE))
    sql=sql.replace("__END__","COMMIT" if a.apply else "ROLLBACK")
    result=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],
        input=sql.encode("utf-8"),env=env,capture_output=True)
    print(result.stdout.decode("utf-8",errors="replace"))
    if result.stderr: print(result.stderr.decode("utf-8",errors="replace"),file=sys.stderr)
    return result.returncode

if __name__=="__main__":
    try: sys.exit(main())
    except (OSError,ValueError,KeyError) as err:
        print("ERROR:",err,file=sys.stderr)
        sys.exit(1)
