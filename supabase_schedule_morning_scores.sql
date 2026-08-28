-- Clock for FunTech daily morning scores.
-- GitHub Actions remains the worker (score + SMTP). This Postgres job is the
-- scheduler: 08:30 Asia/Kolkata = 03:00 UTC, Monday–Friday.
--
-- Run once in the Supabase SQL editor AFTER you create a GitHub fine-grained
-- PAT with permission Actions: Read and write on FunTech-Stock-Screener.
-- Store that PAT in Vault (Dashboard → Project Settings → Vault) with the
-- exact name: github_workflow_pat
--   or uncomment the create_secret line below (do not commit the token).

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- select vault.create_secret('PASTE_GITHUB_PAT_HERE', 'github_workflow_pat', 'Dispatch Daily morning scores');

select cron.unschedule(jobid)
from cron.job
where jobname in ('funtech-morning-scores', 'funtech-morning-scores-test');

select cron.schedule(
  'funtech-morning-scores',
  '0 3 * * 1-5',
  $$
  select net.http_post(
    url := 'https://api.github.com/repos/vkiyer9691-spec/FunTech-Stock-Screener/actions/workflows/morning-digest.yml/dispatches',
    headers := jsonb_build_object(
      'Accept', 'application/vnd.github+json',
      'Authorization', 'Bearer ' || (
        select decrypted_secret from vault.decrypted_secrets where name = 'github_workflow_pat' limit 1
      ),
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'funtech-morning-scores'
    ),
    body := '{"ref":"main","inputs":{"quick":"false"}}'::jsonb,
    timeout_milliseconds := 15000
  );
  $$
);

-- Confirm it is registered:
-- select jobid, jobname, schedule, active from cron.job;
