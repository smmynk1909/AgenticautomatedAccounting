-- Reference copy — authoritative version lives in
-- migrations/versions/0004_finance.py (upgrade()). Keep in sync on change.
--
-- doc 11 §7: DEFERRABLE INITIALLY DEFERRED constraint trigger enforcing
-- every journal entry's lines balance (Σdr = Σcr) by end-of-transaction.

CREATE OR REPLACE FUNCTION check_journal_balance() RETURNS TRIGGER AS $$
DECLARE
    v_entry_id UUID;
    v_sum_dr NUMERIC(14,2);
    v_sum_cr NUMERIC(14,2);
BEGIN
    v_entry_id := COALESCE(NEW.entry_id, OLD.entry_id);
    SELECT COALESCE(SUM(dr), 0), COALESCE(SUM(cr), 0)
      INTO v_sum_dr, v_sum_cr
      FROM journal_lines WHERE entry_id = v_entry_id;
    IF v_sum_dr <> v_sum_cr THEN
        RAISE EXCEPTION
            'journal entry % does not balance: dr=% cr=%', v_entry_id, v_sum_dr, v_sum_cr;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_balance
AFTER INSERT OR UPDATE OR DELETE ON journal_lines
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION check_journal_balance();
