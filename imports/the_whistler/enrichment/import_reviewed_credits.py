#!/usr/bin/env python3
"""Import individually approved, existing-person Whistler credits.

Read-only dry-run is default. --apply commits one transaction.
No new person/episode creation; unresolved claims must be reviewed separately.
"""
from __future__ import annotations
import argparse,csv,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
sys.path.insert(0,str(REPO/"imports"/"the_whistler"))
from import_the_whistler import read_env,quote

SQL=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.whistler.reviewed.credits'));
CREATE TEMP TABLE inp AS SELECT * FROM jsonb_to_recordset(__PAYLOAD__::jsonb)
 AS x(catalog_id text, episode_id bigint, air_date date, title text,
      person text, person_id bigint, role text);
DO $check$
BEGIN
 IF EXISTS(SELECT 1 FROM inp i LEFT JOIN public.episode e ON e.episode_id=i.episode_id
 WHERE e.episode_id IS NULL OR e.series_id IS DISTINCT FROM (SELECT series_id FROM public.series WHERE slug='the-whistler' LIMIT 1)
 OR e.air_date IS DISTINCT FROM i.air_date
 OR public.otr_title_match_key(e.title) IS DISTINCT FROM public.otr_title_match_key(i.title))
 THEN RAISE EXCEPTION 'Episode identity/date/title mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM inp i LEFT JOIN public.person p ON p.person_id=i.person_id
 WHERE p.person_id IS NULL OR lower(trim(p.display_name))<>lower(trim(i.person)))
 THEN RAISE EXCEPTION 'Contributor identity mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM inp i LEFT JOIN public.credit_type ct ON ct.credit_type=i.role
 WHERE ct.credit_type IS NULL) THEN RAISE EXCEPTION 'Unknown credit type'; END IF;
END $check$;
INSERT INTO public.source(source_type,title,citation,notes)
SELECT 'catalog','Whistler 556-entry user-supplied CBS catalog extract',
 'Reviewed catalog observations by catalog ID',
 'Source-reported credits; excludes non-network versions and audio properties.'
WHERE NOT EXISTS (SELECT 1 FROM public.source
 WHERE title='Whistler 556-entry user-supplied CBS catalog extract');
INSERT INTO public.episode_credit(episode_id,person_id,credit_type,billing_order,notes)
SELECT i.episode_id,i.person_id,i.role,NULL,
 'Source-reported Whistler catalog credit; manually approved; catalog IDs: ' ||
 string_agg(DISTINCT i.catalog_id,', ' ORDER BY i.catalog_id)
FROM inp i WHERE NOT EXISTS(SELECT 1 FROM public.episode_credit ec
 WHERE ec.episode_id=i.episode_id AND ec.person_id=i.person_id AND ec.credit_type=i.role)
GROUP BY i.episode_id,i.person_id,i.role;
INSERT INTO public.entity_source(source_id,entity_type,entity_id,source_role,confidence,notes)
SELECT s.source_id,'episode_credit',ec.episode_credit_id,'catalog_observation','medium',
 'Source-reported reviewed catalog IDs: '||string_agg(DISTINCT i.catalog_id,', ' ORDER BY i.catalog_id)
FROM inp i JOIN public.episode_credit ec
 ON ec.episode_id=i.episode_id AND ec.person_id=i.person_id AND ec.credit_type=i.role
JOIN public.source s ON s.title='Whistler 556-entry user-supplied CBS catalog extract'
GROUP BY s.source_id,ec.episode_credit_id
ON CONFLICT(source_id,entity_type,entity_id,source_role) DO NOTHING;
SELECT count(*) AS approved_observations FROM inp;
__END__;
"""

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--input",type=Path,default=HERE/"credit_candidates.csv")
 p.add_argument("--env",type=Path,default=REPO/".env")
 p.add_argument("--apply",action="store_true")
 a=p.parse_args()
 with a.input.open(encoding="utf-8-sig",newline="") as f:
  rows=list(csv.DictReader(f))
 approved=[r for r in rows if (r.get("approved") or "").strip().lower() in ("yes","true","1")]
 if not approved:
  print("No approved=yes rows; no changes to import.",file=sys.stderr)
  return 2
 payload=[]
 seen=set()
 for r in approved:
  if not str(r.get("person_id","")).isdigit() or not str(r.get("episode_id","")).isdigit():
   raise ValueError(f"Approve only reviewed existing person and episode IDs: {r.get('catalog_id')}")
  if r.get("credit_status")=="candidate_new_person":
   raise ValueError("New-person claims are blocked until identity review")
  key=(r["episode_id"],r["person_id"],r["role"])
  if key in seen: continue
  seen.add(key)
  payload.append(dict(catalog_id=r["catalog_id"],episode_id=int(r["episode_id"]),
      air_date=r["episode_date"],title=r["episode_title"],
      person=r["person"],person_id=int(r["person_id"]),role=r["role"]))
 cfg=read_env(a.env)
 env=os.environ.copy()
 env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
    PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],
    PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
 sql=SQL.replace("__PAYLOAD__",quote(json.dumps(payload,ensure_ascii=False)))
 sql=sql.replace("__END__","COMMIT" if a.apply else "ROLLBACK")
 print(f"Mode: {'APPLY' if a.apply else 'DRY RUN'}; approved unique credits: {len(payload)}",flush=True)
 return subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],
   input=sql,text=True,env=env).returncode

if __name__=="__main__":
 try: sys.exit(main())
 except (OSError,ValueError,KeyError) as e:
  print("ERROR:",e,file=sys.stderr);sys.exit(1)
