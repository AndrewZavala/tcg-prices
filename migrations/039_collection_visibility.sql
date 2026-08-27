-- Collection visibility (private / unlisted / public) and optional share slug.

ALTER TABLE collections
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

ALTER TABLE collections
  ADD COLUMN IF NOT EXISTS share_slug TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'collections_visibility_check'
  ) THEN
    ALTER TABLE collections
      ADD CONSTRAINT collections_visibility_check
      CHECK (visibility IN ('private', 'unlisted', 'public'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'collections_share_slug_format'
  ) THEN
    ALTER TABLE collections
      ADD CONSTRAINT collections_share_slug_format
      CHECK (
        share_slug IS NULL
        OR (
          char_length(share_slug) BETWEEN 3 AND 48
          AND share_slug ~ '^[a-z0-9][a-z0-9-]*$'
        )
      );
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_collections_share_slug
  ON collections (share_slug)
  WHERE share_slug IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_collections_public_updated
  ON collections (updated_at DESC)
  WHERE visibility = 'public';
