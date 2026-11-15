CREATE TABLE IF NOT EXISTS links (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(16)  NOT NULL UNIQUE,
    target_url   TEXT         NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'clean', 'malicious')),
    verdict      TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    checked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS links_status_idx ON links (status);
