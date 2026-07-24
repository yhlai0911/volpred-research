-- Service-role-only exact WorkItem read model for remote Change Delivery.
--
-- The public wrapper returns one bounded snapshot from private FORCE-RLS
-- coordination state. It exposes no mutation surface and grants no direct
-- table or view access to the service role.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_work_snapshot(
  p_work_id text
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT jsonb_build_object(
    'schema_version', 'work-snapshot.v1',
    'items',
      COALESCE(
        (
          SELECT jsonb_agg(to_jsonb(item_row) ORDER BY item_row.id)
          FROM volpred_ops.work_item_reads AS item_row
          WHERE item_row.id = btrim(p_work_id)
        ),
        '[]'::jsonb
      ),
    'events',
      COALESCE(
        (
          SELECT jsonb_agg(
            jsonb_build_object(
              'work_id', event_row.work_id,
              'kind', event_row.kind,
              'version', event_row.version,
              'created_at', event_row.created_at,
              'actor_ref', event_row.actor_ref,
              'evidence_ref', event_row.evidence_ref
            )
            ORDER BY event_row.sequence
          )
          FROM volpred_ops.work_events AS event_row
          WHERE event_row.work_id = btrim(p_work_id)
        ),
        '[]'::jsonb
      ),
    'checkpoints',
      COALESCE(
        (
          SELECT jsonb_agg(
            jsonb_build_object(
              'id', checkpoint_row.id,
              'work_id', checkpoint_row.work_id,
              'artifact_ref', checkpoint_row.artifact_ref,
              'artifact_sha256', checkpoint_row.artifact_sha256,
              'verification_ref', checkpoint_row.verification_ref,
              'created_at', checkpoint_row.created_at
            )
            ORDER BY checkpoint_row.created_at, checkpoint_row.id
          )
          FROM volpred_ops.work_checkpoints AS checkpoint_row
          WHERE checkpoint_row.work_id = btrim(p_work_id)
        ),
        '[]'::jsonb
      ),
    'receipts',
      COALESCE(
        (
          SELECT jsonb_agg(
            jsonb_build_object(
              'id', receipt_row.id,
              'work_id', receipt_row.work_id,
              'outcome', receipt_row.outcome,
              'result_ref', receipt_row.result_ref,
              'summary', receipt_row.summary,
              'created_at', receipt_row.created_at
            )
            ORDER BY receipt_row.created_at, receipt_row.id
          )
          FROM volpred_ops.work_receipts AS receipt_row
          WHERE receipt_row.work_id = btrim(p_work_id)
        ),
        '[]'::jsonb
      )
  )
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER FUNCTION public.volpred_read_work_snapshot(text)
  OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION public.volpred_read_work_snapshot(text)
  FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.volpred_read_work_snapshot(text)
  TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
