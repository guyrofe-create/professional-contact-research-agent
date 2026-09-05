# Research status

Open the repository's **Actions** tab and select **Autonomous Contact Research**.

The workflow is scheduled every six hours at minute 17 (Asia/Jerusalem) and can also be started manually with **Run workflow**. It no longer dispatches an immediate duplicate continuation run.

Progress is persisted in `output/checkpoint.jsonl`. Completed tables are written to `output/audit.xlsx` and `output/contacts.xlsx`; totals are in `output/summary.json`.

Each scheduled run uses `--resume`. Version-7 through version-11 checkpoints are migrated losslessly to version 12. Safe verified contacts remain verified, while questionable legacy attributions are rechecked and their previous candidate evidence is retained. Resolved targets are skipped, never-searched rows are not delayed by stale backoff timestamps, and a fair category round-robin prevents starvation. Six bounded workers process targets concurrently. Provider-specific circuit breakers, a shared search budget and a persistent successful-page cache reduce wasted work.

Progress is committed remotely every 50 processed targets or 15 minutes, as well as at the end of a run. Active runs are not cancelled by a newly queued run. `contacts.xlsx` remains the complete deduplicated contact set; separate personal, organizational and shared workbooks prevent an organizational route from being reported as a personal address.

GitHub Actions artifacts from each run are uploaded as `contact-research-<run id>` for monitoring/download. `FINAL` files are replaced only after every target is resolved and the generated workbooks pass validation.

## Email notifications
GitHub can email workflow completion/failure notifications according to the account's Actions notification settings. Direct attachment delivery to a separate mailbox requires mail-provider credentials stored as repository secrets; those credentials are intentionally not committed to this repository.
