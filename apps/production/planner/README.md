# Planner: MVP 1, deployed online TODO

Implementation status: **prepared, suspended; production acceptance pending**.
The target is phase 1 in Planner PR [#3](https://forgejo.colddev.net/coldb/planner/pulls/3),
validated source `c3b1098b36e25186168859d15f623e028e287521`. No production
credentials or application image have been published by this change.

This adds production-only web/API, a three-instance PostgreSQL 17 CNPG cluster,
separate runtime/migration/bootstrap credentials, verified DB TLS, a gated
migration Job, private probes, namespace network policies, a local Cloudflare
tunnel and daily S3 backups. PowerSync, invitation mail/worker, native clients and
the full application dashboard are later deliverables.

## Layout and prerequisites

`clusters/production/planner.yaml` defines four suspended Flux Kustomizations:
`planner-config` → `planner-database` → `planner-migrations` → `planner-web`.
Each waits for the production root `flux-system` Kustomization to apply the
current Git artifact.
The root production GitRepository recursively discovers this file, like
`ledgerly-app.yaml`; do not add the leaf resources to the generic app/database
aggregates as well. Config and database pruning are disabled, and the Cluster
also has a prune opt-out to protect the namespace, credentials and database.
Manual deletion still needs care. Completed migration Jobs remain until the next
release replaces them; no TTL or forced recreation reruns them continually.

Before activation:

1. Fill/encrypt the [seven secret templates](../../../config/production/planner/secrets/README.md).
2. Review a supported Kubernetes/CNPG/PostgreSQL patch combination. Read-only
   inspection on 2026-11-17 found Kubernetes `v1.33.3+k3s1`, CNPG `1.25.0`
   (chart `0.23.0`) and Flux kustomize-controller `v1.9.5`. The [CNPG 1.30
   support matrix](https://cloudnative-pg.io/docs/1.30/supported_releases/)
   lists Kubernetes 1.34–1.36 as supported and 1.33 as tested only. Upgrade
   the shared Kubernetes/CNPG stack separately before activating Planner, and
   confirm the selected operator supports the native Barman API in these manifests.
   CNPG 1.32 and later require migrating native backups to the Barman Cloud plugin.
3. The manifests pin PostgreSQL 17.12 with Barman Cloud tooling and cloudflared
   2026.10.2 by digest. Verify the PostgreSQL pin against the selected operator
   and use the current 17.x patch at activation if it has changed.
4. Confirm Longhorn/node capacity. Each of three DB instances requests 2Gi, and
   `longhorn-retain` currently makes three physical replicas per PVC: roughly
   18Gi before snapshots, overhead and growth. Required pod anti-affinity needs
   three schedulable nodes. Expand retained PVCs before filling them. WAL settings
   are bounded initial targets, not a hard disk-usage cap: failed archiving can
   still accumulate WAL and requires operator attention.
5. Create/verify the S3 bucket/prefix `s3://production-backup-planner-db/v1` and
   access. Use an otherwise empty destination for a fresh cluster. Retention is
   Barman's chain-aware 7-day recovery window, retaining required base/WAL files;
   do not apply an independent seven-object or seven-day deletion rule.
6. Configure the dedicated Clerk production instance in invitation-only mode,
   with `https://planner.colddev.net` as the intended origin/redirect. Use its
   public publishable key at image build time and backend key only at runtime.
7. Create a locally managed Cloudflare tunnel, configure its UUID and JSON Secret,
   and register DNS with `cloudflared tunnel route dns <UUID> planner.colddev.net`.
   Validate local rules using `cloudflared tunnel --config <config> ingress validate`
   and `... ingress rule https://planner.colddev.net/health/ready`.
   Do not add an interactive Access challenge to Planner API requests. HTTPS at
   the edge and encrypted tunnel transport still leave the private origin HTTP.
8. Verify every k3s node trusts the private Forgejo registry CA as described in
   the root README. The namespace-local registry Secret needs package-read scope.

The network policy denies all ingress/egress by default, then allows tunnel → web,
web/migrations/operator → database, replicas, CNPG operator, DNS and monitoring.
Web can reach public HTTPS for Clerk. The tunnel reaches Cloudflare's two global
IPv4 edge pools on TCP/UDP 7844. The database can reach public HTTPS for S3 and
the two observed Kubernetes API addresses, `10.43.0.1:443` before service DNAT
and `192.168.88.195:6443` after it. Verify these addresses after the Kubernetes
upgrade. Standard NetworkPolicy has no hostname selector for Clerk or S3.
Confirm effective CNI enforcement, DNS, API DNAT, replica catch-up and
provider/S3 access in production. Verify that Prometheus discovers the CNPG
PodMonitor through the Planner namespace's monitoring label.

## Build and identify a release

Build from a clean archive of the reviewed Planner commit, with a digest-pinned
Node 24 LTS Debian base satisfying Planner's pinned toolchain. The Dockerfile
copies only explicit source inputs, never `.env` files. One image contains the
web server, SQL, pinned migration tools, operator CLI and database launcher.
The launcher is included in the image digest used by both web and migrations.
The web Deployment receives the runtime database role and Clerk backend key.

Set `planner_publishable_key` to the intended Clerk instance's public key.
Run this block in Bash from the homelab root. It stops before publishing if the
archive or build fails, even if the release tag already exists locally.

```bash
(
  set -euo pipefail
  : "${planner_publishable_key:?Set the Clerk publishable key}"
  planner_source_dir=$(mktemp -d)
  trap 'rm -r -- "$planner_source_dir"' EXIT

  planner_revision=c3b1098b36e25186168859d15f623e028e287521
  planner_release=rc3b1098-1
  planner_image="forgejo.colddev.net/coldb/planner:$planner_release"

  git -C ../planner archive "$planner_revision" | tar -x -C "$planner_source_dir"
  docker build -f "$PWD/apps/production/planner/Dockerfile" \
    --build-context planner-launch="$PWD/apps/production/planner" \
    --build-arg VITE_CLERK_PUBLISHABLE_KEY="$planner_publishable_key" \
    -t "$planner_image" "$planner_source_dir"
  docker push "$planner_image"
  docker buildx imagetools inspect "$planner_image"
)
```

Publishing requires a package-write identity in the operator's Docker login.
The build uses the Dockerfile's pinned Node base, public npm access,
`pnpm@10.32.1` and the lockfile. Supply only the Clerk publishable key at build time.
Retain the resulting registry digest, source SHA, Node base digest, publishable
key's instance and schema `todo-1` as release provenance. A publishable-key change
requires a rebuild. Record validation before promoting the exact same bytes.

In `apps/production/planner-release/kustomization.yaml`, set the published image
digest and the new Job name, such as `planner-migrate-rc3b1098-1`. Web and
migrations read the same component. The Job suffix starts with `r`, ends in
a letter or digit, and uses lowercase letters, digits and hyphens. Use a new
name when changing image, writer, CA or Job settings. Review the SQL in the
source revision and preserve the dataset generation on ordinary releases.

The migration Job runs Planner's reviewed SQL under its session lock and
transactional Drizzle journal. The wrapper serializes migration and verification,
then checks dataset `todo-1`. The runtime role can read/insert lists, read,
insert and update identities, and read/write items. It can read the dataset
generation and has no journal access. Review grants alongside future tables
and operations.

The built-in Flux dependencies compare the dependency's Ready condition,
observed generation and last applied revision with the current Git artifact
when both use the same source. Web waits for both the production root and
migrations. The root applies the child Kustomizations first. The migration
Kustomization waits for the release's Job to complete on that artifact.
A previously completed Job on the previous artifact cannot authorize a new
web digest. Flux keeps the current completed Job until a newer release
replaces it.

Prepare every release in one Git revision. Review additive changes for
compatibility with the currently running web image while the new migration
runs. On failure inspect the Job and SQL, keep the live compatible web image,
and fix forward with a new Job name. To roll back application code, select a
known schema-compatible image, give it a new Job name, and use the same gate.
Reusing a Job name with different immutable settings fails the apply.

## Validate and activate

```sh
python3 scripts/planner/check.py          # Requires Python PyYAML and kubectl
python3 scripts/planner/check.py --ready  # After secrets, pins and UUID are filled
```

The first command checks suspended preparation. `--ready` permits activated
configuration and checks the completed inputs; neither command applies anything.
For first activation, after reviewing/committing the completed inputs, change
only `planner-config.spec.suspend` to false in Git, reconcile and verify its
secrets. Next enable `planner-database`, verify all three instances, managed-role
password reconciliation, CA and backup destination. Then enable migrations and
web in Git. Explicitly use `--context homelab-prod` for runtime commands:

```sh
flux --context homelab-prod reconcile kustomization flux-system -n flux-system --with-source
flux --context homelab-prod reconcile kustomization planner-config -n flux-system --with-source
flux --context homelab-prod get kustomizations -n flux-system
kubectl --context homelab-prod -n planner get cluster planner-db -o yaml
kubectl --context homelab-prod -n planner get jobs,pods,scheduledbackups,backups
kubectl --context homelab-prod -n planner logs job/planner-migrate-<release>
kubectl --context homelab-prod -n planner rollout status deployment/planner-web
kubectl --context homelab-prod -n planner logs deployment/planner-web
kubectl --context homelab-prod -n planner logs deployment/planner-tunnel
```

Private startup/readiness require database/schema access; liveness checks process
responsiveness. Check private health via a port-forward to `service/planner-web`
on port 80. The connector readiness probe reports edge connectivity and the
process can retry connectivity during an outage. Public `/health/*` and `/metrics` must return 404 from the tunnel;
also test encoded/normalized path variants against the selected cloudflared
version before enabling general access. Database and health/metrics Services
have no public ingress. Kubelet probes rely on the CNI's node-probe behavior.

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
   Update the existing encrypted `planner-backup` Secret and IAM scope if they
   still cover only the original prefix. Reconcile `planner-config` before
   bootstrap. After creation, verify Kubernetes API and S3 egress, replication,
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
   schedule targeting the replacement.
   CNPG treats an existing schedule's `spec.cluster` as immutable. Verify role
   password reconciliation and the replacement's first backup at its new prefix.
4. In the same cutover revision, set the shared release component's writer and
   CA to `planner-db-restore-rw.planner.svc.cluster.local` and
   `planner-db-restore-ca`. Choose a new migration Job name. Run the activation
   checker from this revision to verify the recovery, CA and schedule. Keep
   migrations and web suspended until `planner-database` is Ready on that Git revision.
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

Prepared manifests and local checks do not satisfy those production gates. See
[validation evidence](validation.md) for checks actually performed by this change.

## Primary references

- [CNPG bootstrap SQL](https://cloudnative-pg.io/docs/1.25/bootstrap/),
  [recovery and target selection](https://cloudnative-pg.io/docs/1.25/recovery/),
  [WAL archiving](https://cloudnative-pg.io/docs/1.25/wal_archiving/),
  [managed roles](https://cloudnative-pg.io/docs/1.25/declarative_role_management/) and
  [Barman integration](https://cloudnative-pg.io/docs/1.25/backup_barmanobjectstore/)
  describe the API available in the inspected operator; revalidate after upgrade.
- [Flux dependency expressions](https://fluxcd.io/flux/components/kustomize/kustomizations/#dependency-ready-expression)
  describe the readiness/release gate.
- [Cloudflare local configuration](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
  describes the ordered ingress rules used to keep health paths private.
