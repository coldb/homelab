# MVP 1 homelab validation

On 2026-11-18, the Planner PR #3 head was
`c3b1098b36e25186168859d15f623e028e287521` according to
`git ls-remote origin refs/pull/3/head`. The build used a clean `git archive`
of that commit and the launcher from this homelab branch.

| Check | Observed result |
| --- | --- |
| `python3 scripts/planner/check.py` | All four suspended paths rendered |
| Activation checker with temporary SOPS fixtures | Accepted all seven rendered encrypted Secrets. Rejected an omitted Secret subdirectory and wrong rendered key. Both modes rejected a Secret with encrypted `stringData` and plaintext `data` |
| Secret runbook with temporary files | Installed all seven outputs after encryption. A late placeholder, an injected encryption failure and scanner exit 127 returned nonzero and preserved all seven previous outputs |
| Restore preflight with rendered replacement manifests | Accepted the recovery Cluster, its CA, separate archive prefix and new enabled schedule. Rejected a retained Cluster in the overlay, mismatched CA, reused or disabled schedule, fresh `initdb`, missing owner settings and a reused backup destination |
| Operator Job rendered from an archived release | Used the replacement writer, CA and image digest from the selected revision despite an uncommitted writer change in the local checkout |
| Operator cutover commands with stubbed Kubernetes responses | Only the Ready replacement revision with a matching writer reached mock create. The command blocked a migration that became stale, failed, suspended or unobserved after rendering |
| `flux build kustomization ... --dry-run` | The production root discovered all four Planner Kustomizations. Migration and web rendered the same release image, writer and CA |
| Flux v1.9.5 `checkDependencies` with a fake Kubernetes client | Blocked a new source behind the stale root, then behind an old completed migration. Also blocked an unobserved generation and a failed migration. Passed once both dependencies were Ready on the new artifact |
| Docker build from clean Planner source | Node 24.22.3 and pnpm 10.32.1 built a local image using a fixture public Clerk key |
| Release runbook commands with stubbed Docker | Archive or build failure exited nonzero and made zero push calls. A failed push skipped inspection. Success ran build, push and inspect in order. Each path cleaned up the archive |
| Disposable PostgreSQL 17 with TLS | Fresh, repeated and concurrent migrations completed with a URL-special-character password. A different dataset generation, wrong CA and wrong service hostname were rejected |
| Partial migration failure and corrected retry | The migration launcher returned nonzero on SQLSTATE `22012`. Both pending schema changes rolled back and the migration journal matched its pre-run contents. The corrected retry applied both migrations exactly once |
| Database authorization | Runtime has item DML, reads/inserts lists and cannot delete identities, modify lists, write datasets, read the journal or create objects |
| Planner service with the deployed runtime grants | Created the first private list and added, edited, completed, reopened and deleted an item |
| Manual operator | Runtime role successfully performed status, admit, disable and status |
| Restored admission fixture | A row representing an older admission allowed a synthetic authenticated identity. Reapplying the recorded Planner-only disablement with the operator CLI caused the real API handler to return 403 for reads and writes using the same identity fixture |
| Nonroot web with a read-only filesystem | Startup, readiness and liveness returned 200 with a fixture Clerk configuration and the migrated database |
| PostgreSQL image inspection | The digest-pinned CNPG image ran PostgreSQL 17.12 and Barman Cloud 3.20.1 |
| Planned cutover WAL switch with disposable PostgreSQL 17 | The SQL returned the exact segment the fixture archiver stored. Production S3 receipt was not exercised |
| cloudflared image inspection | The digest-pinned image validated the ingress config as UID 65532 with a read-only filesystem |

The migration check uses Flux's built-in dependency logic. Controller v1.9.5
checks Ready, observed generation and the dependency's last applied revision
against the current source artifact when the dependency shares that source.
Every Planner Kustomization shares the root GitRepository and waits for the
root on that artifact. Web also waits for migrations on the same artifact.
The dependency cases used the branch's actual manifests and ran inside the
pinned controller package. Live reconciliation remains a production acceptance
check. [Controller implementation](https://github.com/fluxcd/kustomize-controller/blob/v1.9.5/internal/controller/kustomization_controller.go#L558-L629)

For the partial-failure check, disposable PostgreSQL 17.12 first ran the three
reviewed migrations through the container's normal `node /app/launch.mjs migrate`
entrypoint. A temporary read-only copy of `apps/web/drizzle` added two pending
migrations and two journal metadata entries. The first created a fixture table and
inserted a row. The second added a column, inserted a second row, then ran
`SELECT 1/0`. After the failure, `to_regclass('planner.release_fixture')` was
null and the ordered `(hash, created_at)` journal rows matched the baseline.
Removing the failing statement and retrying produced both fixture rows and the
two expected journal hashes. A repeat changed neither. The probe and runtime
checks still passed. The extra SQL was mounted only in the disposable fixture.

Production inspection was read-only. It observed Kubernetes `v1.33.3+k3s1`,
CNPG `1.25.0`, Flux kustomize-controller `v1.9.5`, and an expandable retained
Longhorn class with three storage replicas. These observations identify the
rollout prerequisites in the runbook. Local tests did not use production
credentials, and the validation image was kept local.

Production acceptance still requires a supported Kubernetes/CNPG combination,
user-filled SOPS Secrets, publishing and pulling the Planner image, a working
Clerk instance and tunnel, effective network controls, measured capacity,
production migration/restart checks, and actual S3 backups with recoverable
history. The [release runbook](README.md) records those gates. Planner's
application delivery tracker should receive the production evidence once those
checks have run.
