#!/usr/bin/env python3
"""Generate deterministic PostgreSQL X Minus One upserts from the master CSV."""
import csv, json, sys
from pathlib import Path

src = Path(sys.argv[1]) if len(sys.argv)>1 else Path('x_minus_one_master_timeline.csv')
out = Path(sys.argv[2]) if len(sys.argv)>2 else Path('upsert_x_minus_one.sql')
with src.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
assert len(rows)==145, f'Expected 145 timeline events, received {len(rows)}'
assert len({(r['air_date'],r['event_type']) for r in rows})==len(rows),'Duplicate date/event combination: review before import'
canonical=[r for r in rows if r['event_type']=='broadcast' and r['broadcast_status']!='repeat']
assert len(canonical)==114
seen=set()
number_conflicts=[]
for r in canonical:
 if r['episode_number'] in seen:
  number_conflicts.append((r['air_date'],r['episode_number'],r['title']))
  r['effective_episode_number']=-int(r['air_date'].replace('-',''))
  r['catalog_episode_number']=None
 else:
  seen.add(r['episode_number'])
  r['effective_episode_number']=int(r['episode_number'])
  r['catalog_episode_number']=int(r['episode_number'])
assert len({r['effective_episode_number'] for r in canonical})==114
assert number_conflicts==[('1957-01-23','79','Open Warfare')], number_conflicts
for r in rows:
 if 'effective_episode_number' not in r:
  r['effective_episode_number']=int(r['repeat_of_episode']) if r['repeat_of_episode'] else (None if r['broadcast_status']=='repeat' else (int(r['episode_number']) if r['episode_number'] else None))
  r['catalog_episode_number']=int(r['episode_number']) if r['episode_number'] else None
assert all(sum(e['catalog_episode_number'] == int(r['repeat_of_episode']) for e in canonical) == 1 for r in rows if r['broadcast_status']=='repeat' and r['repeat_of_episode'])
assert all(r['air_date'] and len(r['air_date'])==10 for r in rows)
for r in rows:
 r['broadcast_sequence']=int(r['broadcast_sequence']) if r['broadcast_sequence'] else None
 r['episode_number']=int(r['episode_number']) if r['episode_number'] else None
 r['repeat_of_episode']=int(r['repeat_of_episode']) if r['repeat_of_episode'] else None
payload=json.dumps(rows,ensure_ascii=False,separators=(',',':'))
assert '$xmo_data$' not in payload
sql=r'''-- Generated from the X Minus One consolidated master. PostgreSQL 15+.
-- Apply on an existing otr.db installation. Transactional, re-runnable, no schema changes.
-- 114 originals/audition/revival => episode; all 145 timeline entries => broadcast.
-- Two repeat target IDs are unresolved: stored as broadcast events with NULL episode_id.
-- Duplicate source episode 79 is retained as a separate canonical row with NULL series_episode_number
-- and a provisional negative legacy identity (-19570123); requires later research.
-- No people are fabricated: author/adapter strings are retained in notes for subsequent identity reconciliation.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(hashtext('otr.x_minus_one.import.v1'));

CREATE TEMP TABLE xmo_stage ON COMMIT DROP AS
SELECT * FROM jsonb_to_recordset($xmo_data$__PAYLOAD__$xmo_data$::jsonb) AS x(
 broadcast_sequence integer, air_date date, event_type text, broadcast_status text,
 episode_number integer, repeat_of_episode integer, effective_episode_number integer, catalog_episode_number integer, title text, description text,
 original_author text, adapted_by text, feature_type text, source_work_title text,
 broadcast_note text, description_source text, dated_sources text, date_sources text, review_flag text
);

DO $check$
BEGIN
 IF (SELECT count(*) FROM xmo_stage) <> 145 THEN RAISE EXCEPTION 'Expected 145 timeline rows'; END IF;
 IF (SELECT count(*) FROM xmo_stage WHERE event_type='broadcast' AND broadcast_status <> 'repeat') <> 114 THEN
  RAISE EXCEPTION 'Expected 114 distinct canonical episode records'; END IF;
 IF EXISTS (SELECT 1 FROM xmo_stage WHERE event_type='broadcast' AND broadcast_status <> 'repeat' GROUP BY effective_episode_number HAVING count(*) > 1) THEN
  RAISE EXCEPTION 'Duplicate canonical episode numbers'; END IF;
 -- A repeat with no repeat_of_episode is unresolved historical evidence, not a bad FK.
 -- Reject only supplied references that cannot resolve to exactly one canonical episode.
 IF EXISTS (
   SELECT 1 FROM xmo_stage s
   WHERE s.broadcast_status='repeat'
     AND s.repeat_of_episode IS NOT NULL
     AND (SELECT count(*) FROM xmo_stage o
          WHERE o.event_type='broadcast' AND o.broadcast_status <> 'repeat'
            AND o.catalog_episode_number = s.repeat_of_episode) <> 1
 ) THEN
   RAISE EXCEPTION 'Repeat references an invalid or ambiguous canonical episode number';
 END IF;
 IF EXISTS (SELECT 1 FROM public.series WHERE slug='x-minus-one' AND name IS DISTINCT FROM 'X Minus One') THEN
  RAISE EXCEPTION 'Conflicting series slug x-minus-one'; END IF;
 -- Never overlay an unrelated legacy record or numeric episode number.
 IF EXISTS (SELECT 1 FROM public.episode e JOIN public.series s ON e.series_id=s.series_id
            JOIN xmo_stage x ON e.series_episode_number ~ '^[0-9]+$'
             AND e.series_episode_number::bigint=x.catalog_episode_number
            WHERE s.slug='x-minus-one' AND x.event_type='broadcast' AND x.broadcast_status <> 'repeat'
              AND (e.legacy_system IS DISTINCT FROM 'X_MINUS_ONE' OR e.legacy_episode_id IS DISTINCT FROM x.effective_episode_number)) THEN
    RAISE EXCEPTION 'Existing episode-number collision with non-X_MINUS_ONE catalog record'; END IF;
 IF EXISTS (SELECT 1 FROM public.episode e JOIN xmo_stage x ON e.legacy_system='X_MINUS_ONE'
            AND e.legacy_episode_id=x.effective_episode_number
            WHERE x.event_type='broadcast' AND x.broadcast_status <> 'repeat'
              AND e.series_id IS DISTINCT FROM (SELECT series_id FROM public.series WHERE slug='x-minus-one')) THEN
    RAISE EXCEPTION 'Conflicting X_MINUS_ONE legacy identity'; END IF;
END $check$;

INSERT INTO public.series(slug,name,network,start_date,end_date,description)
VALUES('x-minus-one','X Minus One','NBC','1955-04-22','1958-01-09',
       'NBC science-fiction radio anthology; audition and 1973 revival represented separately.')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO public.episode(
 series_id,series_episode_number,air_date,title,description,broadcast_status,feature_type,
 legacy_system,legacy_episode_id,note)
SELECT s.series_id, x.catalog_episode_number::text, x.air_date, NULLIF(x.title,''), NULLIF(x.description,''),
 x.broadcast_status, NULLIF(x.feature_type,''),'X_MINUS_ONE',x.effective_episode_number,
 concat_ws(E'\n',
   CASE WHEN x.catalog_episode_number IS NULL THEN 'REVIEW: source episode number 79 conflicts with another original; internal legacy identity is a provisional negative date key.' END,
   NULLIF('Original author(s): ' || nullif(x.original_author,''), 'Original author(s): '),
   NULLIF('Adapted by: ' || nullif(x.adapted_by,''), 'Adapted by: '),
   NULLIF('Source work: ' || nullif(x.source_work_title,''), 'Source work: '),
   NULLIF('Description source: ' || nullif(x.description_source,''), 'Description source: '),
   NULLIF('Dated sources: ' || nullif(x.dated_sources,''), 'Dated sources: '))
FROM xmo_stage x CROSS JOIN public.series s
WHERE s.slug='x-minus-one' AND x.event_type='broadcast' AND x.broadcast_status <> 'repeat'
ON CONFLICT (legacy_system,legacy_episode_id) DO UPDATE SET
  title=EXCLUDED.title, air_date=EXCLUDED.air_date,
  description=COALESCE(EXCLUDED.description,public.episode.description),
  broadcast_status=EXCLUDED.broadcast_status,
  feature_type=COALESCE(EXCLUDED.feature_type,public.episode.feature_type),
  note=EXCLUDED.note,
  updated_at=CASE WHEN (public.episode.title,public.episode.air_date,public.episode.description,
                    public.episode.broadcast_status,public.episode.feature_type,public.episode.note)
                  IS DISTINCT FROM (EXCLUDED.title,EXCLUDED.air_date,
                     COALESCE(EXCLUDED.description,public.episode.description),EXCLUDED.broadcast_status,
                     COALESCE(EXCLUDED.feature_type,public.episode.feature_type),EXCLUDED.note)
                  THEN now() ELSE public.episode.updated_at END;

-- Broadcast mapping: original/audition/revival => original; repeat => repeat;
-- confirmed hiatus/preemption => no_episode; uncertain interruption => other.
CREATE TEMP TABLE xmo_broadcast_stage ON COMMIT DROP AS
SELECT s.series_id, x.air_date,
 CASE WHEN x.event_type='broadcast' AND x.broadcast_status='repeat' THEN 'repeat'
      WHEN x.event_type='broadcast' THEN 'original'
      WHEN x.broadcast_status IN ('Preemption','Documented hiatus','Hiatus',
                                 'Preemption / special programming','Preemption / network interruption')
           THEN 'no_episode'
      ELSE 'other' END AS broadcast_type,
 CASE WHEN x.event_type='broadcast' THEN x.broadcast_sequence ELSE NULL END AS sequence_number,
 CASE WHEN x.event_type='broadcast' THEN e.episode_id ELSE NULL END AS episode_id,
 NULLIF(x.title,'') AS title,
 concat_ws(E'\n',
   'Master status: ' || x.broadcast_status,
   CASE WHEN x.repeat_of_episode IS NOT NULL THEN 'Repeat of episode: ' || x.repeat_of_episode::text
        WHEN x.broadcast_status='repeat' THEN 'REVIEW: repeat target unresolved; source episode number: ' || COALESCE(x.episode_number::text,'unknown') END,
   NULLIF(x.broadcast_note,''),
   CASE WHEN x.review_flag='True' THEN 'Review flag: true' END,
   NULLIF('Date evidence: ' || nullif(x.date_sources,''),'Date evidence: ')) AS note
FROM xmo_stage x CROSS JOIN public.series s
LEFT JOIN public.episode e
 ON e.series_id=s.series_id AND e.legacy_system='X_MINUS_ONE'
 AND e.legacy_episode_id=x.effective_episode_number
WHERE s.slug='x-minus-one';

DO $check$
BEGIN
 IF EXISTS (SELECT 1 FROM xmo_broadcast_stage WHERE broadcast_type='original' AND episode_id IS NULL) THEN
   RAISE EXCEPTION 'Broadcast references a missing canonical episode'; END IF;
 -- Refuse ambiguity before updating: only one existing row is allowed per planned date/type.
 IF EXISTS (SELECT 1 FROM public.broadcast b JOIN xmo_broadcast_stage x ON b.series_id=x.series_id
      AND b.air_date=x.air_date AND b.broadcast_type=x.broadcast_type
      GROUP BY x.air_date,x.broadcast_type HAVING count(*) > 1) THEN
   RAISE EXCEPTION 'Ambiguous existing broadcasts for a planned X Minus One date/type'; END IF;
 IF EXISTS (SELECT 1 FROM public.broadcast b JOIN xmo_broadcast_stage x ON b.series_id=x.series_id
      AND b.air_date=x.air_date WHERE b.broadcast_type IS DISTINCT FROM x.broadcast_type) THEN
   RAISE EXCEPTION 'Existing broadcast event conflicts with the master status; review first'; END IF;
END $check$;

UPDATE public.broadcast b SET
 episode_id=x.episode_id, sequence_number=x.sequence_number, title=x.title,
 note=x.note, updated_at=CASE WHEN (b.episode_id,b.sequence_number,b.title,b.note)
       IS DISTINCT FROM (x.episode_id,x.sequence_number,x.title,x.note)
       THEN now() ELSE b.updated_at END
FROM xmo_broadcast_stage x
WHERE b.series_id=x.series_id AND b.air_date=x.air_date AND b.broadcast_type=x.broadcast_type
  AND (b.episode_id,b.sequence_number,b.title,b.note) IS DISTINCT FROM
      (x.episode_id,x.sequence_number,x.title,x.note);

INSERT INTO public.broadcast(series_id,episode_id,sequence_number,air_date,title,note,broadcast_type,legacy_system)
SELECT x.series_id,x.episode_id,x.sequence_number,x.air_date,x.title,x.note,x.broadcast_type,'X_MINUS_ONE'
FROM xmo_broadcast_stage x
WHERE NOT EXISTS (SELECT 1 FROM public.broadcast b WHERE b.series_id=x.series_id AND b.air_date=x.air_date);

-- One documented, master-dataset level source; no fabricated external URLs.
INSERT INTO public.source(source_type,title,citation,notes)
SELECT 'dataset','X Minus One reconciled broadcast master (2026-10)',
       'Consolidated from three user-provided X Minus One datasets',
       'Broadcast date/title evidence in stage files; consult review issues for disputed claims.'
WHERE NOT EXISTS (SELECT 1 FROM public.source WHERE source_type='dataset'
  AND title='X Minus One reconciled broadcast master (2026-10)');

INSERT INTO public.entity_source(source_id,entity_type,entity_id,source_role,confidence,notes)
SELECT src.source_id,'episode',e.episode_id,'catalog_source',
       CASE WHEN x.review_flag='True' THEN 'medium' ELSE 'high' END,
       'Master episode '||x.episode_number::text||'; date sources: '||COALESCE(x.date_sources,'')
FROM xmo_stage x
JOIN public.episode e ON e.legacy_system='X_MINUS_ONE' AND e.legacy_episode_id=x.effective_episode_number
CROSS JOIN public.source src
WHERE x.event_type='broadcast' AND x.broadcast_status <> 'repeat'
AND src.title='X Minus One reconciled broadcast master (2026-10)'
AND NOT EXISTS(SELECT 1 FROM public.entity_source es
 WHERE es.source_id=src.source_id AND es.entity_type='episode' AND es.entity_id=e.episode_id AND es.source_role='catalog_source');

DO $verify$
DECLARE ecount integer; bcount integer;
BEGIN
 SELECT count(*) INTO ecount FROM public.episode e JOIN public.series s USING(series_id)
 WHERE s.slug='x-minus-one' AND e.legacy_system='X_MINUS_ONE';
 SELECT count(*) INTO bcount FROM public.broadcast b JOIN public.series s USING(series_id)
 WHERE s.slug='x-minus-one';
 IF ecount<>114 THEN RAISE EXCEPTION 'Expected 114 canonical episodes, got %',ecount; END IF;
 IF bcount<>145 THEN RAISE EXCEPTION 'Expected 145 timeline events, got %',bcount; END IF;
END $verify$;

SELECT broadcast_type,count(*) AS events FROM public.broadcast b JOIN public.series s USING(series_id)
WHERE s.slug='x-minus-one' GROUP BY broadcast_type ORDER BY broadcast_type;
COMMIT;
'''.replace('__PAYLOAD__',payload)
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(sql,encoding='utf-8')
print('Generated',out,'events',len(rows),'canonical',len(canonical),'review conflicts',number_conflicts)
