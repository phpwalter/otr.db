-- CBSRMT legacy appearance -> global episode_credit migration
-- Prerequisite: migrate the legacy CBSRMT episode table into global episode first,
-- setting episode.legacy_system='CBSRMT' and episode.legacy_episode_id=<old episode id>.
-- The old tables are referenced as legacy_appearance(id, cast_id, episode_id).

BEGIN;

INSERT INTO episode_credit (
    episode_id, person_id, credit_type, billing_order, notes,
    legacy_system, legacy_credit_id
)
SELECT
    e.episode_id,
    a.cast_id::bigint,
    'actor',
    NULL,
    NULL,
    'CBSRMT',
    a.id::bigint
FROM legacy_appearance a
JOIN episode e
  ON e.legacy_system = 'CBSRMT'
 AND e.legacy_episode_id = a.episode_id::bigint
JOIN person p
  ON p.person_id = a.cast_id::bigint
ON CONFLICT (legacy_system, legacy_credit_id) DO NOTHING;

COMMIT;
