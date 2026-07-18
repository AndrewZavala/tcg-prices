-- Add packed status between planned (need to pack) and sent (shipped / awaiting payment).

ALTER TABLE ck_fulfillments
    DROP CONSTRAINT IF EXISTS ck_fulfillments_status_check;

ALTER TABLE ck_fulfillments
    ADD CONSTRAINT ck_fulfillments_status_check CHECK (
        status IN ('planned', 'packed', 'sent', 'paid', 'rejected', 'cancelled')
    );

ALTER TABLE ck_fulfillments
    ADD COLUMN IF NOT EXISTS packed_at TIMESTAMPTZ;
