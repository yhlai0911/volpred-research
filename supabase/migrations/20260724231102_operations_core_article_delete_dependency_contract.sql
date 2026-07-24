-- Fail-closed catalog readout for publisher article destructive recovery.
--
-- The legacy delete reconciler must capture every row that Postgres would
-- remove through ON DELETE CASCADE.  This narrow service-role-only function
-- lets the runtime compare the live FK graph with its checked-in recovery
-- allowlist before any destructive mutation.  A newly added cascade therefore
-- blocks deletion until recovery support is deliberately added.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION
  public.volpred_read_article_delete_dependency_contract()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'table', child.relname,
        'column', attribute.attname,
        'on_delete',
          CASE constraint_row.confdeltype
            WHEN 'a' THEN 'no_action'
            WHEN 'r' THEN 'restrict'
            WHEN 'c' THEN 'cascade'
            WHEN 'n' THEN 'set_null'
            WHEN 'd' THEN 'set_default'
            ELSE 'unknown'
          END
      )
      ORDER BY child.relname, attribute.attname
    ),
    '[]'::jsonb
  )
  FROM pg_catalog.pg_constraint AS constraint_row
  JOIN pg_catalog.pg_class AS child
    ON child.oid = constraint_row.conrelid
  JOIN pg_catalog.pg_namespace AS child_namespace
    ON child_namespace.oid = child.relnamespace
  JOIN pg_catalog.unnest(constraint_row.conkey)
    WITH ORDINALITY AS key_column(attnum, ordinal_position)
    ON true
  JOIN pg_catalog.pg_attribute AS attribute
    ON attribute.attrelid = constraint_row.conrelid
   AND attribute.attnum = key_column.attnum
  WHERE constraint_row.contype = 'f'
    AND constraint_row.confrelid = 'public.articles'::regclass
    AND child_namespace.nspname = 'public';
$$;

ALTER FUNCTION
  public.volpred_read_article_delete_dependency_contract()
  OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_read_article_delete_dependency_contract()
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_read_article_delete_dependency_contract()
TO service_role;

COMMENT ON FUNCTION
  public.volpred_read_article_delete_dependency_contract()
IS
  'Service-role-only live FK contract for fail-closed article delete recovery.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
