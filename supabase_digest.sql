-- Optional columns for morning-digest opt-in.
-- Run in the Supabase SQL editor if you want cloud persistence of the checkbox.
-- The app still stores the same preference in data/digest_prefs.json locally.

alter table if exists public.user_settings
  add column if not exists digest_opt_in boolean default false,
  add column if not exists digest_top_n integer default 10;
