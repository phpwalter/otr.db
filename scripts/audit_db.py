#!/usr/bin/env python3
"""Read-only OTR database audit; uses updater's existing .env parser and source loader."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_updater():
    path = ROOT / 'scripts' / 'update_fisher_by_episode.py'
    spec = importlib.util.spec_from_file_location('fisher_updater', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Updater not found: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def query_dict(cur, sql, params=()):
    cur.execute(sql, params)
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, help='Fisher .csv/.json used for the successful import')
    p.add_argument('--series-id', type=int, default=1)
    p.add_argument('--env', type=Path, default=ROOT / '.env')
    p.add_argument('--dsn', help='Override .env; avoid passing passwords on command line')
    p.add_argument('--report', type=Path, default=ROOT / 'reports' / 'otr-database-audit.json')
    args = p.parse_args()
    if args.series_id < 1:
        p.error('--series-id must be positive')
    updater = load_updater()
    source = updater.read_records(args.source) if args.source else None
    con = updater.connect(updater.get_dsn(args.dsn, args.env))
    result = {'source_records': len(source) if source else None, 'fisher': {}, 'constraints': {}, 'integrity': {}, 'completeness': {}, 'migrations': {}}
    try:
        with con.cursor() as cur:
            cur.execute('BEGIN READ ONLY')
            result['constraints']['declared'] = query_dict(cur, '''
                SELECT n.nspname AS schema_name, c.relname AS table_name,
                       x.conname AS constraint_name, x.contype AS kind,
                       pg_get_constraintdef(x.oid) AS definition
                FROM pg_constraint x
                JOIN pg_class c ON c.oid=x.conrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND x.contype IN ('p','f','u','c')
                ORDER BY c.relname,x.conname''')
            result['constraints']['unvalidated'] = query_dict(cur, '''
                SELECT conrelid::regclass::text AS table_name, conname
                FROM pg_constraint WHERE NOT convalidated AND connamespace='public'::regnamespace''')
            result['integrity']['duplicate_numeric_episode_numbers'] = query_dict(cur, '''
                SELECT series_id,series_episode_number::bigint AS episode_number,count(*) AS copies
                FROM public.episode
                WHERE series_episode_number ~ '^[0-9]+$'
                GROUP BY series_id,series_episode_number::bigint HAVING count(*)>1
                ORDER BY series_id,episode_number''')
            result['integrity']['broadcast_cross_series'] = query_dict(cur, '''
                SELECT b.broadcast_id,b.series_id AS broadcast_series,e.series_id AS episode_series
                FROM public.broadcast b JOIN public.episode e ON e.episode_id=b.episode_id
                WHERE b.series_id<>e.series_id ORDER BY b.broadcast_id LIMIT 100''')
            result['integrity']['run_cross_series'] = query_dict(cur, '''
                SELECT e.episode_id,e.series_id AS episode_series,r.series_id AS run_series
                FROM public.episode e JOIN public.series_run r ON r.series_run_id=e.series_run_id
                WHERE e.series_id<>r.series_id ORDER BY e.episode_id LIMIT 100''')
            result['integrity']['unresolved_cbsrmt_issues'] = query_dict(cur, '''
                SELECT issue_type,count(*) AS total FROM public.import_issue
                WHERE source_system='CBSRMT' AND resolved_at IS NULL GROUP BY issue_type ORDER BY issue_type''')
            result['completeness']['by_series'] = query_dict(cur, '''
                SELECT s.series_id,s.name, count(e.episode_id) AS total_episodes,
                count(e.episode_id) FILTER (WHERE nullif(btrim(e.title),'') IS NULL) AS missing_title,
                count(e.episode_id) FILTER (WHERE e.air_date IS NULL) AS missing_air_date,
                count(e.episode_id) FILTER (WHERE nullif(btrim(e.description),'') IS NULL) AS missing_description,
                count(e.episode_id) FILTER (WHERE e.fisher_rubric IS NOT NULL) AS fisher_rated,
                count(e.episode_id) FILTER (WHERE e.fisher_cast_roles IS NOT NULL) AS fisher_cast
                FROM public.series s LEFT JOIN public.episode e ON e.series_id=s.series_id
                GROUP BY s.series_id,s.name ORDER BY s.series_id''')
            result['completeness']['episodes_without_credits_by_series'] = query_dict(cur, '''
                SELECT e.series_id,count(*) AS episodes_without_credits
                FROM public.episode e WHERE NOT EXISTS
                (SELECT 1 FROM public.episode_credit c WHERE c.episode_id=e.episode_id)
                GROUP BY e.series_id ORDER BY e.series_id''')
            result['completeness']['episodes_without_writers_by_series'] = query_dict(cur, '''
                SELECT e.series_id,count(*) AS episodes_without_writers
                FROM public.episode e WHERE NOT EXISTS
                (SELECT 1 FROM public.episode_credit c WHERE c.episode_id=e.episode_id AND c.credit_type='writer')
                GROUP BY e.series_id ORDER BY e.series_id''')
            result['completeness']['episodes_without_sources_by_series'] = query_dict(cur, '''
                SELECT e.series_id,count(*) AS episodes_without_sources
                FROM public.episode e WHERE NOT EXISTS
                (SELECT 1 FROM public.entity_source es WHERE es.entity_type='episode' AND es.entity_id=e.episode_id)
                GROUP BY e.series_id ORDER BY e.series_id''')
            result['integrity']['orphaned_entity_sources'] = query_dict(cur, '''
                SELECT es.entity_source_id,es.entity_type,es.entity_id FROM public.entity_source es
                WHERE (es.entity_type='episode' AND NOT EXISTS (SELECT 1 FROM public.episode e WHERE e.episode_id=es.entity_id))
                   OR (es.entity_type='person' AND NOT EXISTS (SELECT 1 FROM public.person p WHERE p.person_id=es.entity_id))
                   OR (es.entity_type='series' AND NOT EXISTS (SELECT 1 FROM public.series s WHERE s.series_id=es.entity_id))
                   OR (es.entity_type='episode_credit' AND NOT EXISTS (SELECT 1 FROM public.episode_credit c WHERE c.episode_credit_id=es.entity_id))
                ORDER BY es.entity_source_id LIMIT 100''')
            cur.execute("SELECT to_regclass('public.otr_migration_history')")
            if cur.fetchone()[0] is not None:
                result['migrations']['history'] = query_dict(cur, '''
                    SELECT script_path,category,checksum_sha256,manual,applied_at,execution_ms
                    FROM public.otr_migration_history ORDER BY script_path''')
            else:
                result['migrations']['warning'] = 'otr_migration_history not found'
            if source is not None:
                matched,missing,ambiguous,differing,unchanged = 0,[],[],[],0
                for number,expected in source.items():
                    rows = query_dict(cur, '''
                        SELECT episode_id,fisher_rubric,fisher_cast_roles FROM public.episode
                        WHERE series_id=%s AND series_episode_number ~ '^[0-9]+$'
                        AND series_episode_number::bigint=%s''', (args.series_id,int(number)))
                    if len(rows)==0:
                        missing.append(number)
                    elif len(rows)>1:
                        ambiguous.append(number)
                    else:
                        matched+=1
                        current=rows[0]
                        differences={field:{'expected':str(value),'actual':str(current[field])}
                            for field,value in expected.items() if current[field]!=value}
                        if differences:
                            differing.append({'episode_number':number,'fields':differences})
                        else:
                            unchanged+=1
                result['fisher']={'matched':matched,'unchanged':unchanged,'missing':missing,
                                  'ambiguous':ambiguous,'differing':differing}
            con.rollback()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,default=str)+'\n',encoding='utf-8')
    print('REPORT', args.report)
    if source is not None:
        f=result['fisher']
        print(f"FISHER source={len(source)} matched={f['matched']} unchanged={f['unchanged']} missing={len(f['missing'])} ambiguous={len(f['ambiguous'])} differing={len(f['differing'])}")
    for section, name in [('integrity','duplicate_numeric_episode_numbers'),('integrity','broadcast_cross_series'),('integrity','run_cross_series'),('integrity','orphaned_entity_sources'),('integrity','unresolved_cbsrmt_issues'),('constraints','unvalidated')]:
        print(f'CHECK {name}: {len(result[section][name])}')
    problems=sum(len(result[section][name]) for section,name in [('integrity','duplicate_numeric_episode_numbers'),('integrity','broadcast_cross_series'),('integrity','run_cross_series'),('integrity','orphaned_entity_sources'),('integrity','unresolved_cbsrmt_issues'),('constraints','unvalidated')])
    if source is not None:
        problems+=len(result['fisher']['missing'])+len(result['fisher']['ambiguous'])+len(result['fisher']['differing'])
    return 1 if problems else 0

if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'AUDIT ERROR: {exc}',file=sys.stderr)
        sys.exit(2)
