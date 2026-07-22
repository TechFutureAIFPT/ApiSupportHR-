-- SupportHR Firebase -> Supabase foundation.
-- Safe to re-run: tables, indexes, grants, policies, and publication entries are idempotent.

create extension if not exists pgcrypto;
create extension if not exists vector;

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'profiles',
    'user_settings',
    'google_drive_connections',
    'google_drive_oauth_states',
    'user_sync_state',
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
    'mobile_inbox_views',
    'approved_exemplars',
    'vector_library_records',
    'desktop_sessions',
    'session_commands',
    'candidate_schedules'
  ]
  loop
    execute format(
      'create table if not exists public.%I (
        id text primary key,
        owner_id uuid references auth.users(id) on delete set null,
        legacy_uid text,
        payload jsonb not null default ''{}''::jsonb,
        source_payload jsonb not null default ''{}''::jsonb,
        source_collection text,
        source_document_id text,
        source_checksum text,
        source_created_at timestamptz,
        source_updated_at timestamptz,
        migrated_at timestamptz not null default now(),
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        status text,
        job_position text,
        action text,
        file_type text,
        collection_key text,
        expires_at timestamptz,
        secret_payload bytea,
        unique (source_collection, source_document_id)
      )',
      table_name
    );
    execute format('create index if not exists %I on public.%I (owner_id)', table_name || '_owner_idx', table_name);
    execute format('create index if not exists %I on public.%I (updated_at desc)', table_name || '_updated_idx', table_name);
    execute format('create index if not exists %I on public.%I using gin (payload jsonb_path_ops)', table_name || '_payload_gin', table_name);
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on public.%I from anon', table_name);
    execute format('grant select, insert, update, delete on public.%I to authenticated', table_name);
  end loop;
end
$$;
alter table public.vector_library_records
  add column if not exists legacy_embedding double precision[],
  add column if not exists embedding vector(768),
  add column if not exists embedding_model text,
  add column if not exists vector_index_version text;

alter table public.approved_exemplars
  add column if not exists legacy_embedding double precision[],
  add column if not exists embedding vector(768),
  add column if not exists embedding_model text,
  add column if not exists vector_index_version text,
  add column if not exists rubric_version text,
  add column if not exists approved boolean not null default false;

create index if not exists vector_library_records_embedding_hnsw
  on public.vector_library_records using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

create index if not exists approved_exemplars_embedding_hnsw
  on public.approved_exemplars using hnsw (embedding vector_cosine_ops)
  where embedding is not null and approved = true;

create table if not exists public.legacy_identity_map (
  firebase_uid text primary key,
  supabase_user_id uuid unique references auth.users(id) on delete set null,
  email text,
  match_method text not null check (match_method in ('uid', 'email', 'unresolved')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.legacy_identity_map enable row level security;
revoke all on public.legacy_identity_map from anon, authenticated;

create table if not exists public.migration_runs (
  id uuid primary key default gen_random_uuid(),
  source_project text,
  archive_checksum text not null,
  status text not null default 'running',
  source_summary jsonb not null default '{}'::jsonb,
  result_summary jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.migration_documents (
  run_id uuid not null references public.migration_runs(id) on delete cascade,
  source_system text not null,
  source_collection text not null,
  source_document_id text not null,
  source_checksum text not null,
  target_table text,
  target_id text,
  owner_id uuid,
  status text not null,
  error text,
  migrated_at timestamptz not null default now(),
  primary key (run_id, source_system, source_collection, source_document_id)
);

create table if not exists public.migration_unresolved_owners (
  run_id uuid not null references public.migration_runs(id) on delete cascade,
  source_system text not null,
  source_collection text not null,
  source_document_id text not null,
  legacy_uid text,
  legacy_email text,
  reason text not null,
  created_at timestamptz not null default now(),
  primary key (run_id, source_system, source_collection, source_document_id)
);

create table if not exists public.legacy_rtdb_chatbot_sessions (
  id text primary key,
  owner_id uuid references auth.users(id) on delete set null,
  legacy_uid text,
  session_id text not null,
  payload jsonb not null,
  source_checksum text not null,
  migrated_at timestamptz not null default now(),
  unique (legacy_uid, session_id)
);

alter table public.migration_runs enable row level security;
alter table public.migration_documents enable row level security;
alter table public.migration_unresolved_owners enable row level security;
alter table public.legacy_rtdb_chatbot_sessions enable row level security;
revoke all on public.migration_runs from anon, authenticated;
revoke all on public.migration_documents from anon, authenticated;
revoke all on public.migration_unresolved_owners from anon, authenticated;
revoke all on public.legacy_rtdb_chatbot_sessions from anon, authenticated;

-- Owner policies matching the previous Firestore rules.
do $$
declare
  table_name text;
begin
  foreach table_name in array array['profiles', 'jd_templates', 'desktop_sessions', 'session_commands', 'candidate_schedules']
  loop
    execute format('drop policy if exists owner_select on public.%I', table_name);
    execute format('drop policy if exists owner_insert on public.%I', table_name);
    execute format('drop policy if exists owner_update on public.%I', table_name);
    execute format('drop policy if exists owner_delete on public.%I', table_name);
    execute format('create policy owner_select on public.%I for select to authenticated using ((select auth.uid()) = owner_id)', table_name);
    execute format('create policy owner_insert on public.%I for insert to authenticated with check ((select auth.uid()) = owner_id)', table_name);
    execute format('create policy owner_update on public.%I for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id)', table_name);
    execute format('create policy owner_delete on public.%I for delete to authenticated using ((select auth.uid()) = owner_id)', table_name);
  end loop;

  foreach table_name in array array['cv_history', 'synced_analysis_history', 'manual_history', 'user_sync_state']
  loop
    execute format('drop policy if exists owner_select on public.%I', table_name);
    execute format('create policy owner_select on public.%I for select to authenticated using ((select auth.uid()) = owner_id)', table_name);
  end loop;
end
$$;

drop policy if exists owner_insert on public.analysis_feedback;
create policy owner_insert on public.analysis_feedback
  for insert to authenticated
  with check ((select auth.uid()) = owner_id);

-- Add only the three tables used for cross-device realtime coordination.
do $$
declare
  table_name text;
begin
  foreach table_name in array array['desktop_sessions', 'session_commands', 'user_sync_state']
  loop
    if not exists (
      select 1
      from pg_publication_tables
      where pubname = 'supabase_realtime'
        and schemaname = 'public'
        and tablename = table_name
    ) then
      execute format('alter publication supabase_realtime add table public.%I', table_name);
    end if;
  end loop;
end
$$;
