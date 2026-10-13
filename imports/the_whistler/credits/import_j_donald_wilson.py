#!/usr/bin/env python3
"""Import 41 source-reported J. Donald Wilson writer credits into OTR PostgreSQL.

Reads repository-root .env. Default ROLLBACK; --apply commits. Requires explicit
--person-id for identity assurance. Preserves "source-reported" in credit notes
and entity_source; never labels these as independently production verified.
No other episode or person record is modified.
"""
from __future__ import annotations
import argparse,csv,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from import_the_whistler import read_env,quote
ROOT=HERE.parents[2]
SQL=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
SELECT pg_advisory_xact_lock(hashtext('otr.whistler.wilson.writer.v1'));
CREATE TEMP TABLE incoming AS SELECT
 x.number::bigint AS episode_number,x.day::date AS air_date,
 x.title AS title,x.source_title AS source_title,x.method AS match_method
 FROM jsonb_to_recordset(__PAYLOAD__::jsonb)
 AS x(number text,day text,title text,source_title text,method text);
DO $check$
BEGIN
 IF (SELECT count(*) FROM incoming)<>41 OR (SELECT count(DISTINCT episode_number) FROM incoming)<>41
 THEN RAISE EXCEPTION 'Expected 41 distinct Wilson writing observations'; END IF;
 IF (SELECT count(*) FROM public.person WHERE person_id=__PERSON_ID__ AND
      lower(btrim(display_name)) IN ('j. donald wilson','j. donald willson'))<>1
 THEN RAISE EXCEPTION 'Specified --person-id does not identify J. Donald Wilson'; END IF;
 IF EXISTS(SELECT 1 FROM incoming i LEFT JOIN public.episode e ON
 e.legacy_system='THE_WHISTLER' AND e.legacy_episode_id=i.episode_number
 WHERE e.episode_id IS NULL OR e.air_date IS DISTINCT FROM i.air_date OR public.otr_title_match_key(e.title) IS DISTINCT FROM public.otr_title_match_key(i.title))
 THEN RAISE EXCEPTION 'One or more episode identities mismatch database'; END IF;
 IF EXISTS(SELECT 1 FROM incoming i JOIN public.episode e
 ON e.legacy_system='THE_WHISTLER' AND e.legacy_episode_id=i.episode_number
 JOIN public.episode_credit ec ON ec.episode_id=e.episode_id
 WHERE ec.person_id=__PERSON_ID__ AND ec.credit_type='writer'
 AND (ec.billing_order IS NOT NULL OR ec.notes IS DISTINCT FROM
    ('Source-reported writer attribution: J. Donald Wilson; source: The Archive of American Radio filtered writer listing')))
 THEN RAISE EXCEPTION 'Existing writer credit conflicts with source attribution; manual review needed'; END IF;
END $check$;
INSERT INTO public.source(source_type,title,citation,notes)
SELECT 'website','The Archive of American Radio — J. Donald Wilson filtered Whistler results',
 'User-provided 41-result writer-filter listing',
 'Episode-specific writer claims, source-reported; original page URL not supplied.'
WHERE NOT EXISTS (SELECT 1 FROM public.source WHERE
 title='The Archive of American Radio — J. Donald Wilson filtered Whistler results'
 AND citation='User-provided 41-result writer-filter listing');
CREATE TEMP TABLE inserted AS SELECT
 e.episode_id,i.episode_number
 FROM incoming i JOIN public.episode e ON e.legacy_system='THE_WHISTLER'
 AND e.legacy_episode_id=i.episode_number;
INSERT INTO public.episode_credit(episode_id,person_id,credit_type,billing_order,notes)
SELECT i.episode_id,__PERSON_ID__,'writer',NULL,
 'Source-reported writer attribution: J. Donald Wilson; source: The Archive of American Radio filtered writer listing'
 FROM inserted i
 WHERE NOT EXISTS(SELECT 1 FROM public.episode_credit ec WHERE
 ec.episode_id=i.episode_id AND ec.person_id=__PERSON_ID__ AND ec.credit_type='writer');
INSERT INTO public.entity_source(source_id,entity_type,entity_id,source_role,confidence,notes)
SELECT s.source_id,'episode_credit',ec.episode_credit_id,'writer_attribution','medium',
 'Source-reported from user-provided writer-filter listing; not independently production verified.'
FROM inserted i
JOIN public.episode_credit ec ON ec.episode_id=i.episode_id
 AND ec.person_id=__PERSON_ID__ AND ec.credit_type='writer'
JOIN public.source s ON s.title='The Archive of American Radio — J. Donald Wilson filtered Whistler results'
 AND s.citation='User-provided 41-result writer-filter listing'
ON CONFLICT (source_id,entity_type,entity_id,source_role) DO NOTHING;
SELECT count(*) AS mapped_writer_credits FROM inserted;
__END__;
"""
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--input",type=Path,default=HERE/"j_donald_wilson_matched.csv")
 p.add_argument("--env",type=Path,default=ROOT/".env")
 p.add_argument("--person-id",type=int,required=True,help="Existing reviewed J. Donald Wilson person_id")
 modes=p.add_mutually_exclusive_group()
 modes.add_argument("--dry-run",action="store_true");modes.add_argument("--apply",action="store_true")
 a=p.parse_args()
 if a.person_id<=0:raise ValueError("person-id must be positive")
 with a.input.open(encoding="utf-8-sig",newline="") as f:
  rows=list(csv.DictReader(f))
 if len(rows)!=41:raise ValueError("Expected 41 matched records")
 if sum(r.get("match_method")=="reviewed_title_variant" for r in rows)!=1:
  raise ValueError("Expected exactly one reviewed title variation")
 data=[]
 for r in rows:
  if r["person_name"]!="J. Donald Wilson" or r["credit_type"]!="writer":
   raise ValueError("Wrong source person/credit")
  data.append(dict(number=r["episode_number"],day=r["air_date"],title=r["episode_title"],
     source_title=r["source_title"],method=r["match_method"]))
 cfg=read_env(a.env);env=os.environ.copy()
 env.update(PGHOST=cfg["DB_HOST"],PGPORT=cfg["DB_PORT"],PGDATABASE=cfg["DB_NAME"],
  PGUSER=cfg["DB_USER"],PGPASSWORD=cfg["DB_PASSWORD"],PGSSLMODE=cfg.get("DB_SSLMODE","prefer"))
 sql=SQL.replace("__PAYLOAD__",quote(json.dumps(data,ensure_ascii=False))).replace("__PERSON_ID__",str(a.person_id))
 sql=sql.replace("__END__","COMMIT" if a.apply else "ROLLBACK")
 print(f"Mode: {'APPLY' if a.apply else 'DRY RUN'}; Wilson credits: 41; person_id: {a.person_id}",flush=True)
 result=subprocess.run(["psql","-X","-w","-v","ON_ERROR_STOP=1","-f","-"],input=sql,text=True,env=env)
 return result.returncode
if __name__=="__main__":
 try:sys.exit(main())
 except (OSError,ValueError,KeyError) as e:
  print(f"ERROR: {e}",file=sys.stderr);sys.exit(1)
