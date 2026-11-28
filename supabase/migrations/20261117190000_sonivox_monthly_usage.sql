-- SONIVOX: monthly free character allowance with atomic reservations.
-- 20,000 characters per user per UTC calendar month. Payments are not enabled.

create table if not exists public.sonivox_usage_periods (
  user_id uuid not null references auth.users(id) on delete cascade,
  period_start date not null,
  characters_used integer not null default 0 check (characters_used >= 0),
  primary key (user_id, period_start)
);

create table if not exists public.sonivox_usage_reservations (
  request_id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  period_start date not null,
  characters integer not null check (characters > 0),
  status text not null default 'reserved'
    check (status in ('reserved', 'completed', 'refunded')),
  created_at timestamptz not null default now()
);

alter table public.sonivox_usage_periods enable row level security;
alter table public.sonivox_usage_reservations enable row level security;

drop policy if exists "Users can read their own usage" on public.sonivox_usage_periods;
create policy "Users can read their own usage"
  on public.sonivox_usage_periods for select to authenticated
  using ((select auth.uid()) = user_id);

revoke all on public.sonivox_usage_periods, public.sonivox_usage_reservations
  from anon, authenticated;
grant select on public.sonivox_usage_periods to authenticated;

create or replace function public.reserve_sonivox_characters(
  p_request_id uuid, p_characters integer
) returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user uuid := auth.uid();
  v_period date := date_trunc('month', now() at time zone 'utc')::date;
  v_used integer;
  v_limit constant integer := 20000;
begin
  if v_user is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  if p_characters is null or p_characters < 1 or p_characters > 1000 then
    raise exception 'Invalid character amount' using errcode = '22023';
  end if;

  insert into public.sonivox_usage_periods(user_id, period_start, characters_used)
  values (v_user, v_period, 0)
  on conflict (user_id, period_start) do nothing;

  select characters_used into v_used
  from public.sonivox_usage_periods
  where user_id = v_user and period_start = v_period
  for update;

  if v_used + p_characters > v_limit then
    return jsonb_build_object(
      'allowed', false, 'limit', v_limit, 'used', v_used,
      'remaining', greatest(0, v_limit - v_used)
    );
  end if;

  insert into public.sonivox_usage_reservations(
    request_id, user_id, period_start, characters, status
  ) values (p_request_id, v_user, v_period, p_characters, 'reserved');

  update public.sonivox_usage_periods
  set characters_used = characters_used + p_characters
  where user_id = v_user and period_start = v_period;

  return jsonb_build_object(
    'allowed', true, 'limit', v_limit, 'used', v_used + p_characters,
    'remaining', v_limit - v_used - p_characters
  );
end;
$$;

create or replace function public.finish_sonivox_reservation(
  p_request_id uuid, p_success boolean
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_user uuid := auth.uid();
  v_row public.sonivox_usage_reservations%rowtype;
begin
  if v_user is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;

  select * into v_row
  from public.sonivox_usage_reservations
  where request_id = p_request_id and user_id = v_user
  for update;

  if not found or v_row.status <> 'reserved' then
    return false;
  end if;

  if p_success then
    update public.sonivox_usage_reservations
    set status = 'completed'
    where request_id = p_request_id;
  else
    update public.sonivox_usage_periods
    set characters_used = greatest(0, characters_used - v_row.characters)
    where user_id = v_user and period_start = v_row.period_start;

    update public.sonivox_usage_reservations
    set status = 'refunded'
    where request_id = p_request_id;
  end if;

  return true;
end;
$$;

revoke all on function public.reserve_sonivox_characters(uuid, integer)
  from public, anon;
revoke all on function public.finish_sonivox_reservation(uuid, boolean)
  from public, anon;
grant execute on function public.reserve_sonivox_characters(uuid, integer)
  to authenticated;
grant execute on function public.finish_sonivox_reservation(uuid, boolean)
  to authenticated;
