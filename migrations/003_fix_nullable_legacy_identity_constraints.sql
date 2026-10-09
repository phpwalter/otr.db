-- Fix legacy identity uniqueness so non-legacy rows may coexist.
-- Legacy identity is unique only when both source system and legacy ID exist.

BEGIN;

ALTER TABLE person
    DROP CONSTRAINT IF EXISTS person_legacy_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_person_legacy_identity
    ON person(legacy_system, legacy_person_id)
    WHERE legacy_system IS NOT NULL AND legacy_person_id IS NOT NULL;

ALTER TABLE episode
    DROP CONSTRAINT IF EXISTS episode_legacy_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_episode_legacy_identity
    ON episode(legacy_system, legacy_episode_id)
    WHERE legacy_system IS NOT NULL AND legacy_episode_id IS NOT NULL;

ALTER TABLE episode_credit
    DROP CONSTRAINT IF EXISTS episode_credit_legacy_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_episode_credit_legacy_identity
    ON episode_credit(legacy_system, legacy_credit_id)
    WHERE legacy_system IS NOT NULL AND legacy_credit_id IS NOT NULL;

ALTER TABLE broadcast
    DROP CONSTRAINT IF EXISTS broadcast_legacy_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_broadcast_legacy_identity
    ON broadcast(legacy_system, legacy_broadcast_id)
    WHERE legacy_system IS NOT NULL AND legacy_broadcast_id IS NOT NULL;

ALTER TABLE episode_genre
    DROP CONSTRAINT IF EXISTS episode_genre_legacy_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_episode_genre_legacy_identity
    ON episode_genre(legacy_system, legacy_record_id)
    WHERE legacy_system IS NOT NULL AND legacy_record_id IS NOT NULL;

COMMIT;
