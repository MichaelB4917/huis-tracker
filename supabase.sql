-- Eenmalig uitvoeren in Supabase → SQL Editor
create table if not exists public.lijsten (
  id uuid primary key default gen_random_uuid(),
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.lijsten enable row level security;  -- geen policies: tabel niet direct leesbaar

create or replace function public.lijst_get(p_id uuid) returns jsonb
  language sql security definer set search_path = public
  as $$ select data from lijsten where id = p_id $$;
create or replace function public.lijst_new(p_data jsonb) returns uuid
  language sql security definer set search_path = public
  as $$ insert into lijsten(data) values (coalesce(p_data, '{}'::jsonb)) returning id $$;
create or replace function public.lijst_save(p_id uuid, p_data jsonb) returns void
  language sql security definer set search_path = public
  as $$ update lijsten set data = p_data, updated_at = now() where id = p_id $$;

revoke all on function public.lijst_get(uuid), public.lijst_new(jsonb), public.lijst_save(uuid, jsonb) from public;
grant execute on function public.lijst_get(uuid), public.lijst_new(jsonb), public.lijst_save(uuid, jsonb) to anon, authenticated;
