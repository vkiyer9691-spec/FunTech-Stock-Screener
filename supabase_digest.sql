-- Opt-in columns for the Streamlit-hosted app + GitHub Actions digest.
-- Run this once in the Supabase SQL editor (this project).

alter table if exists public.user_settings
  add column if not exists digest_opt_in boolean default false,
  add column if not exists digest_top_n integer default 10;

-- The morning GitHub Action should use the service_role key (GitHub secret
-- SUPABASE_SERVICE_ROLE_KEY) so it can read every opted-in user. Do not put
-- service_role in Streamlit Cloud secrets — keep using the anon key there.

