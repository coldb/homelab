# Planner production deployment

The Planner PostgreSQL cluster is already active in the `planner` namespace.
This overlay adds the web app and API, a database migration Job, a Cloudflare
Tunnel and a manual Job for user admission and disablement.

## Prepare the first release

1. Merge the Planner image PR. A push to Planner’s `main` runs the checks and
   publishes `forgejo.colddev.net/coldb/planner:latest`. Copy the digest from
   the **Check and publish Planner** run summary for the merged commit.
   [Planner repository](https://forgejo.colddev.net/coldb/planner)
2. Configure the Planner production Clerk instance for invitation-only sign-up
   and use `https://planner.colddev.net` as the app origin. Copy its
   `CLERK_PUBLISHABLE_KEY` (`pk_live_…`) and `CLERK_SECRET_KEY` (`sk_live_…`)
   into the Clerk Secret template. The pod reads both keys at runtime.
3. Log in with `cloudflared tunnel login`, then create the locally managed
   tunnel with `cloudflared tunnel create planner`. Set its UUID in
   `cloudflared-config.yaml` and register DNS with
   `cloudflared tunnel route dns <UUID> planner.colddev.net`. Use the generated
   `<UUID>.json` credentials in the tunnel Secret template.
4. Prepare the Forgejo registry pull credentials. Encrypt the Clerk, registry
   and Cloudflare Secret files and add them to the Planner config overlay.
   [Application secrets](../../../config/production/planner/secrets/README.md)
5. In `apps/production/planner-release/kustomization.yaml`, set `newTag` to
   `latest@sha256:<published-digest>`. The release component supplies the same
   image, verified writer hostname and CNPG CA to web, migration and operator
   workloads.

Run the checks from the homelab root with Python, PyYAML and `kubectl`:

```sh
python3 scripts/planner/check.py          # Render the suspended preparation
python3 scripts/planner/check.py --ready  # Check populated release inputs
cloudflared tunnel --config apps/production/planner/cloudflared-config.yaml ingress validate
```

## Enable the workloads

Merge the pinned image and encrypted inputs with `planner-migrations` and
`planner-web` still suspended. Verify that the three new Secrets are present in
`planner`. Then remove `spec.suspend: true` from those two Flux Kustomizations
in `clusters/production/planner.yaml` and reconcile production.

```sh
flux --context homelab-prod reconcile kustomization flux-system -n flux-system --with-source
flux --context homelab-prod get kustomizations -n flux-system
kubectl --context homelab-prod -n planner get jobs,pods
kubectl --context homelab-prod -n planner rollout status deployment/planner-web
kubectl --context homelab-prod -n planner rollout status deployment/planner-tunnel
```

Flux waits for `planner-migrate` to succeed on the same Git revision before
applying the web and tunnel Deployments. Flux recreates this Job when the image
or other immutable fields change. The Job runs the reviewed SQL and verifies
dataset `todo-1`.

For later releases, Renovate proposes the new `latest` digest in a homelab PR.
Review migration compatibility with the running web image before merging. If a
migration fails, review its logs and publish a corrected release. To roll back,
pin a known schema-compatible digest.

Network policies limit web ingress to the Tunnel and let the web, migration
and operator pods reach PostgreSQL. Web can reach public HTTPS for Clerk, and
the Tunnel can reach Cloudflare's IPv4 edge pools on TCP/UDP 7844. Verify the
web health endpoints through a private port-forward to `service/planner-web`
on port 80. Test that public `/health/*` and `/metrics` paths return 404, including
encoded and normalized variants.

## Admission and disablement

Render the manual operator overlay from the last successful production
migration revision. It uses the same release component as web and migrations,
including the writer and CA after a restore. This overlay is manual. The
commands below use `jq`. Set `planner_cutover_revision` and `planner_cutover_writer`
only when running the restore procedure.

```sh
umask 077
planner_operator_dir=$(mktemp -d)
planner_current_migration_revision() {
  kubectl --context homelab-prod -n flux-system get kustomization planner-migrations -o json |
    jq -er --arg cutover "${planner_cutover_revision:-}" '
      select($cutover == "" or (
        .spec.suspend != true and
        .metadata.generation == .status.observedGeneration and
        .status.lastAppliedRevision == $cutover and
        any(.status.conditions[]?; .type == "Ready" and .status == "True")
      )) | .status.lastAppliedRevision | strings | select(length > 0)'
}
planner_migration_revision=$(planner_current_migration_revision) &&
git archive "${planner_migration_revision##*:}" \
  apps/production/planner-operator apps/production/planner-release |
  tar -x -C "$planner_operator_dir" &&
kubectl kustomize "$planner_operator_dir/apps/production/planner-operator" \
  > "$planner_operator_dir/job.yaml"
```

Use the rendered file only after the command succeeds. Fetch the deployed commit
if it is not available locally. Edit the Job's name to be unique, select
`status`, `admit` or `disable`, and pass the stable Clerk `user_…` identity.
Create the Job with the following command, which checks the writer before
submitting a restore Job.

```sh
(
  set -eu
  if [ -n "${planner_cutover_revision:-}" ]; then
    test "$planner_migration_revision" = "$planner_cutover_revision"
    kubectl --context homelab-prod create --dry-run=client \
      -f "$planner_operator_dir/job.yaml" -o json |
      jq -e --arg writer "${planner_cutover_writer:?Set the restored writer hostname}" '
        any(.spec.template.spec.containers[].env[]?; .name == "PGHOST" and .value == $writer)'
    planner_current_migration_revision >/dev/null
  fi
  kubectl --context homelab-prod create -f "$planner_operator_dir/job.yaml"
)
```

Wait for completion, inspect its log and remove the temporary directory. The
Job uses only the runtime database role and the CA.

Invite the first identity in Clerk, verify its stable ID/provider state, inspect
Planner status, then explicitly admit it. No email bootstrap or automatic
re-admission exists. For a planned provider ban/deletion, disable in Planner
first, verify an existing session gets 403 for reads/writes, then change Clerk.
For an out-of-band provider change, resolve the original stable ID, disable it
immediately and verify denial. Retain disabled records. Logins and email reuse
must not undo disablement. Re-admit only by an explicit operator decision after
checking provider state. These are manual procedures in phase 1.
Keep a private record outside the Planner database of each admission or
disablement, its stable identity and timestamp, for the backup retention window.
Include confirmed out-of-band changes after reconciling them in Planner.

## Backup, restore and acceptance

`planner-db-daily` requests an immediate initial backup and then daily execution
at 02:00 UTC (`0 0 2 * * *`, six fields). Inspect Backup status, errors and S3
objects, not just the ScheduledBackup resource. Inspect archiving/retention and
confirm one-week recoverable history accumulates. Retained replicated PVCs are
not database backups. No recovery-time guarantee or restore drill is claimed.

For a manual restore:

1. Suspend Planner web and migration reconciliation in Git. Set
   `spec.suspend: true` on the original ScheduledBackup in Git and reconcile
   it before changing the database overlay. Once Flux applies the workload
   suspension, scale the web and tunnel Deployments to zero to stop access.
   Set the tunnel's replica count to zero in `cloudflared.yaml` for the cutover
   revision so that private web verification can run before public access.
   Pause routine admission Jobs until cutover is complete.
   Preserve the original Cluster, PVCs and archive. Capture current Planner
   admission statuses from the original database if it can still be read.
   For a planned cutover that must preserve all committed writes, wait for web
   Pods and any running migration or operator Jobs to stop. Keep the original
   primary online. Use its local PostgreSQL admin session to run
   `SELECT pg_walfile_name(pg_switch_wal());` and record the segment it returns.
   Verify that exact segment is readable in the source S3 archive before
   starting recovery. The switch alone does not confirm upload. If the primary
   is unavailable, record the recoverable cutoff from the available archive.
2. Choose a recoverable base backup and WAL chain. Pick an unused replacement
   cluster name, such as `planner-db-restore`, and update the network policies
   for both clusters before creating it.
   In every selector on `cnpg.io/cluster` in `network-policies.yaml`, use
   `matchExpressions` with `operator: In` and both cluster names.
   Verify that the recovery credential can
   list and read the source backups and WAL. Before creating the replacement,
   grant its S3 credential permission to list, read, write and delete expired
   objects at the new archive prefix, with any required multipart permissions.
   Extend the IAM scope used by the reflected `aws-backup-credentials` Secret
   to cover the replacement prefix before bootstrap. After creation, verify Kubernetes API and S3 egress, replication,
   and access from the intended clients.
3. **Replace** the original Cluster manifest in the active database overlay
   with the recovery Cluster in the `planner` namespace. The overlay must
   contain only the replacement Cluster. Otherwise Flux also waits for the
   old cluster to become Ready. The database Kustomization's `prune: false`
   preserves the original live Cluster and PVCs when they leave the overlay.
   In `spec.bootstrap.recovery`, set `source` to the `externalClusters` entry
   with the original archive path, server name and read credentials. Set
   `database: planner`, `owner: planner_db_owner` and
   `secret.name: planner-db-owner` so CNPG reconciles the recovered owner with
   the intended credential. Select and record the recovery point before starting.
   To undo an unwanted change, set `recoveryTarget.targetTime` to a known-good
   instant before the change, using a base backup and WAL that cover the target.
   Set `recoveryTarget.backupID` to the chosen Barman backup ID if selecting a
   specific base backup. Verify that the selected backup completed before the
   target and the WAL chain reaches it.
   Omit the target only when you intend to replay through the latest archived WAL.
   Set a new `backup.barmanObjectStore.destinationPath` for the replacement.
   Replace the ScheduledBackup manifest with a new, enabled `planner-db-restore-daily`
   schedule targeting the replacement. Change the `planner-postgresql`
   PodMonitor's `cnpg.io/cluster` selector to the replacement cluster name.
   CNPG treats an existing schedule's `spec.cluster` as immutable. Verify role
   password reconciliation and the replacement's first backup at its new prefix.
4. In the same cutover revision, set the shared release component's writer and
   CA to `planner-db-restore-rw.planner.svc.cluster.local` and
   `planner-db-restore-ca`. Run the activation checker from this revision to
   verify the recovery, CA and schedule. Keep migrations and web suspended
   until `planner-database` is Ready on that Git revision.
   Resume migrations and verify the new Job and restored data.
5. Compare restored admissions by stable identity with current Clerk state and
   newer Planner statuses or operator records. Reapply disablements made after
   the recovery point, including Planner-only disablements. Before running the
   operator commands above, set `planner_cutover_revision` to the expected Flux
   revision (the `main@sha1:…` from the commit that resumes the replacement
   migration), and `planner_cutover_writer` to the replacement writer hostname.
   The render must succeed against that Ready revision. The create command
   verifies the writer and rechecks migration readiness before submission.
   Check each affected identity's status afterward.
   Keep unverifiable restored admissions disabled until explicitly re-admitted.
6. Resume web with the tunnel still at zero replicas. Use a port-forward to the
   private web Service to verify reads and writes are denied for a Planner-disabled
   identity with a valid Clerk session. Supply the stable `X-Planner-Identity`,
   the bearer token and, for writes, `X-Planner-Dataset: todo-1`. Expect HTTP 403.
   Check task operations with an admitted identity. Then restore the normal
   tunnel replica count in Git and remove the old cluster from the client policy
   selectors. Unset the cutover shell variables before routine operator use.
   Retain the original archive and PVCs until you decide to retire them.

Before marking deliverable 1 Done, record dated production evidence here and
update Planner's living `docs/delivery-plan.md`/evidence tracker in its own repo:

- A real admitted identity performs all five actions; reload and web/DB process
  restarts preserve tasks. A second identity cannot access those tasks by UI/API.
- Unadmitted/disabled identities are denied, including an existing session after
  disablement and subsequent provisioning/login. Exercise the out-of-band process.
- A normal image update with matching release migration succeeds and preserves
  tasks; a failed/mismatched migration blocks new web rollout. Repeat/concurrent
  migration runs are safe and do not claim an old Job's success.
- Private probes/logs work, public health/metrics are denied, DB TLS verifies the
  real CA/service name and fails with a wrong CA/hostname. Test network-policy
  denial from an unrelated namespace and required provider/replica/S3 paths.
- Daily backups actually complete, retention is configured as intended, and
  capacity/WAL/archiving are observable. Record actual versions/digests and limits.

## Primary references

- [CNPG bootstrap SQL](https://cloudnative-pg.io/docs/1.30/bootstrap/),
  [recovery and target selection](https://cloudnative-pg.io/docs/1.30/recovery/),
  [WAL archiving](https://cloudnative-pg.io/docs/1.30/wal_archiving/),
  [managed roles](https://cloudnative-pg.io/docs/1.30/declarative_role_management/),
  [monitoring](https://cloudnative-pg.io/docs/1.30/monitoring/) and
  [Barman migration](https://cloudnative-pg.io/plugin-barman-cloud/docs/migration/)
  document the production database configuration and the future backup plugin transition.
- [Flux dependency expressions](https://fluxcd.io/flux/components/kustomize/kustomizations/#dependency-ready-expression)
  describe the readiness/release gate.
- [Cloudflare local configuration](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
  describes the ordered ingress rules used to keep health paths private.
