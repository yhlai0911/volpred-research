-- Immutable, service-role-only live owner attestation for the canonical
-- Operations Core Primary Authority capability.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE TABLE IF NOT EXISTS volpred_ops.primary_authority_ownership (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  capability text NOT NULL
    CHECK (capability = 'operations-core-primary'),
  authority_key text NOT NULL
    CHECK (authority_key = 'operations-core-primary'),
  owner text NOT NULL CHECK (owner = 'operations_core'),
  generation bigint NOT NULL CHECK (generation = 1),
  contract_ref text NOT NULL
    CHECK (contract_ref = 'primary-authority-contract.v1'),
  established_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  established_by text NOT NULL
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM volpred_ops.primary_authority_ownership
    WHERE singleton
  ) THEN
    INSERT INTO volpred_ops.primary_authority_ownership (
      singleton,
      capability,
      authority_key,
      owner,
      generation,
      contract_ref,
      established_by
    )
    VALUES (
      true,
      'operations-core-primary',
      'operations-core-primary',
      'operations_core',
      1,
      'primary-authority-contract.v1',
      'migration:20260727121500'
    );
  END IF;
END;
$$;

DO $$
DECLARE
  row_count bigint;
BEGIN
  SELECT count(*)
  INTO row_count
  FROM volpred_ops.primary_authority_ownership
  WHERE singleton
    AND capability = 'operations-core-primary'
    AND authority_key = 'operations-core-primary'
    AND owner = 'operations_core'
    AND generation = 1
    AND contract_ref = 'primary-authority-contract.v1';
  IF row_count <> 1
     OR (SELECT count(*) FROM volpred_ops.primary_authority_ownership) <> 1 THEN
    RAISE EXCEPTION
      'Primary Authority owner attestation drifted';
  END IF;
END;
$$;

ALTER TABLE volpred_ops.primary_authority_ownership ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_ownership FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS primary_authority_ownership_definer_read
ON volpred_ops.primary_authority_ownership;
CREATE POLICY primary_authority_ownership_definer_read
ON volpred_ops.primary_authority_ownership
FOR SELECT
TO volpred_ops_definer
USING (true);

CREATE OR REPLACE FUNCTION volpred_ops.read_primary_authority_owner()
RETURNS TABLE (
  schema_version text,
  capability text,
  authority_key text,
  owner text,
  generation bigint,
  contract_ref text,
  attested_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT
    'primary-authority-owner.v1'::text,
    ownership.capability,
    ownership.authority_key,
    ownership.owner,
    ownership.generation,
    ownership.contract_ref,
    statement_timestamp()
  FROM volpred_ops.primary_authority_ownership AS ownership
  WHERE ownership.singleton
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_primary_authority_owner()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  owner_payload jsonb;
BEGIN
  SELECT to_jsonb(owner_row)
  INTO STRICT owner_payload
  FROM volpred_ops.read_primary_authority_owner() AS owner_row;
  RETURN owner_payload;
END;
$$;

REVOKE ALL ON TABLE volpred_ops.primary_authority_ownership
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  volpred_ops.read_primary_authority_owner(),
  public.volpred_read_primary_authority_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_primary_authority_owner()
TO service_role;

COMMENT ON TABLE volpred_ops.primary_authority_ownership IS
  'Immutable formal owner record for the canonical Operations Core Primary Authority.';
COMMENT ON FUNCTION public.volpred_read_primary_authority_owner() IS
  'Service-role-only typed live owner attestation; does not acquire or mutate a lease.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
