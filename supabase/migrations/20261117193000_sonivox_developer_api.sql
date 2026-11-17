-- SONIVOX developer API keys and server-side usage reservations.
-- Existing sonivox_api_keys table already has owner RLS and hashed-key columns.
create unique index if not exists sonivox_api_keys_key_hash_uidx
  on public.sonivox_api_keys (key_hash);
create index if not exists sonivox_api_keys_active_prefix_idx
  on public.sonivox_api_keys (key_prefix) where revoked_at is null;

create or replace function public.reserve_sonivox_characters_for_user(
  p_user_id uuid, p_request_id uuid, p_characters integer
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_period date := date_trunc('month', now() at time zone 'utc')::date;
  v_used integer;
  v_limit constant integer := 20000;
begin
  if current_setting('request.jwt.claim.role', true) <> 'service_role' then
    raise exception 'Service role required' using errcode = '42501';
  end if;
  if p_user_id is null or p_request_id is null or p_characters is null
     or p_characters < 1 or p_characters > 1000 then
    raise exception 'Invalid reservation' using errcode = '22023';
  end if;
  insert into public.sonivox_usage_periods(user_id, period_start, characters_used)
  values (p_user_id, v_period, 0)
  on conflict (user_id, period_start) do nothing;
  select characters_used into v_used
  from public.sonivox_usage_periods
  where user_id = p_user_id and period_start = v_period
  for update;
  if v_used + p_characters > v_limit then
    return jsonb_build_object('allowed', false, 'limit', v_limit, 'used', v_used,
      'remaining', greatest(0, v_limit - v_used));
  end if;
  insert into public.sonivox_usage_reservations(request_id,user_id,period_start,characters,status)
  values (p_request_id,p_user_id,v_period,p_characters,'reserved');
  update public.sonivox_usage_periods
  set characters_used = characters_used + p_characters
  where user_id = p_user_id and period_start = v_period;
  return jsonb_build_object('allowed', true, 'limit', v_limit,
    'used', v_used + p_characters, 'remaining', v_limit - v_used - p_characters);
end;
$$;

create or replace function public.finish_sonivox_reservation_for_user(
  p_user_id uuid, p_request_id uuid, p_success boolean
) returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_row public.sonivox_usage_reservations%rowtype;
begin
  if current_setting('request.jwt.claim.role', true) <> 'service_role' then
    raise exception 'Service role required' using errcode = '42501';
  end if;
  select * into v_row from public.sonivox_usage_reservations
  where request_id = p_request_id and user_id = p_user_id for update;
  if not found or v_row.status <> 'reserved' then return false; end if;
  if p_success then
    update public.sonivox_usage_reservations set status='completed'
    where request_id=p_request_id;
  else
    update public.sonivox_usage_periods
    set characters_used=greatest(0,characters_used-v_row.characters)
    where user_id=p_user_id and period_start=v_row.period_start;
    update public.sonivox_usage_reservations set status='refunded'
    where request_id=p_request_id;
  end if;
  return true;
end;
$$;

revoke all on function public.reserve_sonivox_characters_for_user(uuid,uuid,integer) from public, anon, authenticated;
revoke all on function public.finish_sonivox_reservation_for_user(uuid,uuid,boolean) from public, anon, authenticated;
grant execute on function public.reserve_sonivox_characters_for_user(uuid,uuid,integer) to service_role;
grant execute on function public.finish_sonivox_reservation_for_user(uuid,uuid,boolean) to service_role;
