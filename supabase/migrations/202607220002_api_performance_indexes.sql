-- SupportHR API performance indexes and typed timestamp backfill.
-- CONCURRENTLY is intentionally omitted because Supabase migrations run in a transaction.

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'user_settings',
    'cv_history',
    'synced_analysis_history',
    'synced_analysis_cache',
    'uploaded_files',
    'jd_templates',
    'chatbot_sessions',
    'manual_history',
    'analysis_feedback',
    'analysis_jobs',
    'ai_request_history',
    'file_extractions',
    'mobile_jd_standardizations',
    'mobile_quick_cv_analyses',
    'mobile_inbox_views'
  ]
  loop
    execute format(
      'update public.%I
       set source_created_at = coalesce(source_created_at, created_at),
           source_updated_at = coalesce(source_updated_at, updated_at)
       where source_created_at is null or source_updated_at is null',
      table_name
    );
    execute format(
      'create index if not exists %I on public.%I
       (owner_id, (coalesce(source_updated_at, updated_at)) desc, id desc)',
      table_name || '_owner_cursor_idx',
      table_name
    );
  end loop;
end
$$;

create index if not exists uploaded_files_owner_type_cursor_idx
  on public.uploaded_files
  (owner_id, file_type, (coalesce(source_updated_at, updated_at)) desc, id desc);

create index if not exists uploaded_files_owner_session_idx
  on public.uploaded_files
  (owner_id, ((payload ->> 'analysisSessionId')), (coalesce(source_updated_at, updated_at)) desc);

create index if not exists analysis_feedback_owner_action_cursor_idx
  on public.analysis_feedback
  (owner_id, action, (coalesce(source_updated_at, updated_at)) desc, id desc);

create index if not exists analysis_feedback_owner_session_idx
  on public.analysis_feedback (owner_id, ((payload ->> 'sessionId')));

create index if not exists analysis_feedback_owner_history_idx
  on public.analysis_feedback (owner_id, ((payload ->> 'historyId')));

create index if not exists analysis_feedback_owner_sync_history_idx
  on public.analysis_feedback (owner_id, ((payload ->> 'syncHistoryId')));

create index if not exists analysis_feedback_owner_candidate_idx
  on public.analysis_feedback (owner_id, ((payload ->> 'candidateId')));

create index if not exists synced_analysis_cache_owner_cache_key_idx
  on public.synced_analysis_cache (owner_id, ((payload ->> 'cacheKey')));

create index if not exists chatbot_sessions_owner_job_position_idx
  on public.chatbot_sessions
  (owner_id, ((payload ->> 'jobPosition')), (coalesce(source_updated_at, updated_at)) desc);

analyze public.user_settings;
analyze public.cv_history;
analyze public.synced_analysis_history;
analyze public.synced_analysis_cache;
analyze public.uploaded_files;
analyze public.jd_templates;
analyze public.chatbot_sessions;
analyze public.analysis_feedback;
