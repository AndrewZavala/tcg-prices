-- Contact form submissions (bug reports, tagger account requests). Read via psql.

CREATE TABLE IF NOT EXISTS spelltag_contact_messages (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL CHECK (topic IN ('bug', 'tagger', 'other')),
    email TEXT,
    message TEXT NOT NULL,
    user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    handled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_contact_messages_created
    ON spelltag_contact_messages (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_contact_messages_ip_created
    ON spelltag_contact_messages (ip, created_at);
