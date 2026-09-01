# Research status

Open the repository's **Actions** tab and select **Autonomous Contact Research**.

The workflow is scheduled every six hours at minute 17 (Asia/Jerusalem) and can also be started manually with **Run workflow**. It no longer dispatches an immediate duplicate continuation run.

Progress is persisted in `output/checkpoint.jsonl`. Completed tables are written to `output/audit.xlsx` and `output/contacts.xlsx`; totals are in `output/summary.json`.

Each scheduled run uses `--resume`. Resolved targets are skipped, provider-dependent targets use an exponential retry time, and fresh direct-source targets run before retries. The workflow uses a concurrency lock so two research jobs cannot overlap.

GitHub Actions artifacts from each run are uploaded as `contact-research-<run id>` for monitoring/download. `FINAL` files are replaced only after every target is resolved and the generated workbooks pass validation.

## Email notifications
GitHub can email workflow completion/failure notifications according to the account's Actions notification settings. Direct attachment delivery to a separate mailbox requires mail-provider credentials stored as repository secrets; those credentials are intentionally not committed to this repository.
