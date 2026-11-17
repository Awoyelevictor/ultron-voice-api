-- SONIVOX voice presets and preset-bound developer API keys
create table if not exists public.sonivox_voice_presets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  voice_id uuid not null references public.sonivox_voices(id) on delete restrict,
  name text not null check (char_length(name) between 1 and 80),
  settings jsonb not null default '{}'::jsonb check (jsonb_typeof(settings) = 'object'),
  allow_overrides boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id)
);

create unique index if not exists sonivox_voices_id_user_uidx
  on public.sonivox_voices(id,user_id);

alter table public.sonivox_voice_presets
  add constraint sonivox_voice_presets_voice_owner_fk
  foreign key (voice_id,user_id)
  references public.sonivox_voices(id,user_id)
  on delete restrict;

create index if not exists sonivox_voice_presets_owner_idx
  on public.sonivox_voice_presets(user_id, created_at desc);

alter table public.sonivox_voice_presets enable row level security;
revoke all on table public.sonivox_voice_presets from anon;
grant select, insert, update, delete on table public.sonivox_voice_presets to authenticated;

create policy "Users manage own SONIVOX presets"
  on public.sonivox_voice_presets for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

alter table public.sonivox_api_keys
  add column if not exists preset_id uuid references public.sonivox_voice_presets(id) on delete restrict;

alter table public.sonivox_api_keys
  add constraint sonivox_api_keys_preset_owner_fk
  foreign key (preset_id,user_id)
  references public.sonivox_voice_presets(id,user_id)
  on delete restrict;

grant select, insert, update on table public.sonivox_api_keys to authenticated;
