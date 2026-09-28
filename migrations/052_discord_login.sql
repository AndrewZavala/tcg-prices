-- Discord sign-in alongside Google: a user row can hold either or both provider ids.

ALTER TABLE users ALTER COLUMN google_sub DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS discord_id TEXT UNIQUE;
