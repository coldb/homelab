# Production cluster upgrade to K3s 1.36

**Plan only.** Rehearse on `homelab-staging` first. The production target is
K3s **1.36**, CloudNativePG **1.30**, and Longhorn **1.12.2**. Keep the
existing PostgreSQL 17 images and native Barman backup configuration during
this maintenance. Leave Planner suspended until the platform checks pass.

[Longhorn 1.12.2 was tested with Kubernetes 1.36](https://longhorn.io/docs/1.12.2/best-practices/#kubernetes-version).
[CNPG 1.30 supports Kubernetes 1.34 through 1.36](https://cloudnative-pg.io/docs/1.30/supported_releases/).
The intermediate releases below are used to get from the installed versions to
that combination. Recheck the supported versions, release notes, and pins before
scheduling maintenance.

## Starting point

Read-only inventory on 2026-11-18.

| | Staging | Production |
| --- | --- | --- |
| K3s | One server, `lab1`, on `v1.32.5+k3s1` | One server, `prod0`, on `v1.33.3+k3s1`. Three agents on 1.33 and `prod4` on `v1.35.5+k3s1` |
| CloudNativePG | Operator `1.25.0`, chart `0.23.0` | Operator `1.25.0`, chart `0.23.0` |
| PostgreSQL | Forgejo and n8n, one instance each, on 17.2 | Colddev, Forgejo, Ledgerly and n8n on 17.2. Colddev has one instance, the others have three |
| Longhorn | `1.11.1`, V1 volumes. 14 attached and healthy, 5 detached | `1.11.1`, V1 volumes. 25 attached and healthy, 5 detached |

**Staging n8n was blocked at inventory.** The database and application were
recovered on 2026-11-20. See the staging preflight checklist in step 3 for the
remaining entry gates.

**Production is blocked.** Ledgerly reports `walArchivingFailing` and has no
reported last successful backup. Verify a completed backup and its WAL in S3.
Also resolve or explicitly time-box the existing `prod4` version skew under
step 4 before starting production maintenance.

## 1. Prepare backups and lock the versions

1. Identify the K3s datastore and current installation method on each server.
   Record the service configuration, install arguments, current binary version
   and host access required for recovery. Use the per-hop backup method
   below for the datastore in use, including a consistent stopped copy
   for SQLite. Preserve the matching server token separately and securely.
   Verify that these artifacts are accessible off the server and that the restore
   procedure uses the matching K3s version.
   [K3s backup and restore](https://docs.k3s.io/datastore/backup-restore)
2. Repair Ledgerly's WAL archiving as a separate change. Take an on-demand
   CNPG backup of Ledgerly after the repair. For all four production databases,
   record a recent completed base backup and confirm the source archive contains
   the WAL required to recover it. If the planned recovery point must include
   writes through a maintenance cutoff, quiesce the writers, switch WAL on the
   healthy primary and wait for that exact segment to reach the archive.
   [CNPG backup](https://cloudnative-pg.io/docs/1.25/backup/) · [WAL archiving](https://cloudnative-pg.io/docs/1.25/wal_archiving/)
3. Take a Longhorn system backup and wait for `Ready`. Build the recovery
   list from the live PVC-to-volume inventory, including detached volumes
   retained for recovery. Record each critical volume's owner, namespace and
   PVC, volume/PV, expected replicas, backup method, off-cluster artifact ID
   and timestamp, and restore procedure.

   Include the following datasets in the recovery list.

   - Forgejo repositories and other persistent application data.
   - n8n data and persistent application files.
   - Production Rocket.Chat's three `mongod-data-*-rs0-*` PVCs. Use a verified
     MongoDB-native recovery artifact or quiesce MongoDB for a consistent
     Longhorn backup.
   - All CNPG databases under step 2 and the staging entry gate. Account for
     application files separately from database backups.
   - Remaining persistent workloads and monitoring data. Record which volumes
     are rebuildable and how, including caches.

   In the baseline, 7 of 19 staging and 20 of 30 production volumes reported no
   Longhorn backup timestamp, including 15 attached production volumes. Require
   each new Longhorn volume backup to reach `Completed` and verify the artifact
   is readable. In staging, restore a representative backup to a new volume
   and isolated test claim. Mount it in a disposable pod and verify its data
   before removing the test resources. Stop before the first K3s or
   Longhorn change if a critical volume lacks a verified recovery artifact.
   Record the acceptable recovery point and verify backups again at each hop.
   [System backup](https://longhorn.io/docs/1.12.2/advanced-resources/system-backup-restore/backup-longhorn-system/) ·
   [Restore a volume](https://longhorn.io/docs/1.12.2/snapshots-and-backups/backup-and-restore/restore-from-a-backup/)
4. Record Longhorn volume health, replicas, disk headroom, and placement on the
   nodes to be maintained. Investigate degraded or faulted volumes, missing
   replicas, and workloads that cannot move. Reconfirm that volumes are V1.
   If any V2 volumes appear, rework the plan to include their required detach.
   [Longhorn upgrade prechecks](https://longhorn.io/docs/1.12.2/deploy/upgrade/)
5. Record the exact rehearsed pins. These were the K3s channel picks and
   published CNPG chart/operator pairs on 2026-11-18. Keep the bridge releases
   only for their upgrade steps.

| Change in rehearsal order | Candidate version | CNPG Helm chart |
| --- | --- | --- |
| CNPG 1.26 | `1.26.1` | `0.25.0` |
| K3s 1.33 for staging | `v1.33.13+k3s2` | |
| CNPG 1.27 | `1.27.1` | `0.26.1` |
| CNPG 1.28 | `1.28.1` | `0.27.1` |
| K3s 1.34 | `v1.34.13+k3s1` | |
| CNPG 1.29 | `1.29.1` | `0.28.3` |
| CNPG 1.30 | `1.30.2` | `0.29.2` |
| K3s 1.35 | `v1.35.10+k3s1` | |
| Longhorn | `1.12.2` | |
| K3s 1.36 | `v1.36.6+k3s1` | |

Production starts on K3s 1.33 and omits the staging-only K3s hop. Verify the
chart's `appVersion`, CRDs, webhook and RBAC changes at each CNPG hop. Check
the release notes for every intermediate minor and resolve chart or image
availability before publishing any pins to Git. Check K3s packaged addons,
the installed CNI and CSI, and the Flux and workload APIs against each target
minor. Both clusters already run Flux 2.9.5, whose documented compatibility
starts at Kubernetes 1.34.1. Treat the existing 1.32/1.33 period as a bridge
and require successful Flux reconciliation at every chart checkpoint.
[Flux 2.9 compatibility](https://fluxcd.io/blog/2026/06/flux-v2.9.0/)
[K3s channels](https://update.k3s.io/v1-release/channels) ·
[CNPG chart index](https://cloudnative-pg.github.io/charts/index.yaml) ·
[CNPG upgrade guidance](https://cloudnative-pg.io/docs/1.30/installation_upgrade/#upgrades)

**Proceed when** the recovery artifacts, disk headroom, exact pins, maintenance
window, and stop/recovery decisions are recorded. Staging can be rehearsed
while the Ledgerly repair is pending. Production waits for the backup checks.

## 2. Prepare and apply each GitOps chart hop

1. In the target environment's `infrastructure/controllers/<environment>/`
   directory, edit `cloudnativepg/kustomization.yaml` for the `cnpg` HelmRelease
   or `longhorn/kustomization.yaml` for `longhorn`. Add this entry under
   `patches:`, using the release name and that hop's chart version. Retain
   any existing environment patches.

   ```yaml
   - target:
       kind: HelmRelease
       name: cnpg
     patch: |-
       - op: replace
         path: /spec/chart/spec/version
         value: "0.25.0"
   ```

2. Render both environment overlays with `kubectl kustomize` and verify that
   only the intended release pin changes. Render the selected chart with
   the release's effective values and compare the CRDs, controller RBAC
   and webhooks. Both upgrades ship CRDs as Helm templates. Verify they
   roll forward with the existing Flux HelmRelease ownership. Keep the
   CRDs in place. For CNPG 1.30, verify Lease permissions, TLS on the instance
   manager status port and compatibility with any probe or policy using it.
   Review the [CNPG 1.30 upgrade notes](https://cloudnative-pg.io/docs/1.30/installation_upgrade/#upgrading-to-1300-1292-or-1284).
3. Publish one environment-specific hop to `main` at a time. Record that
   commit as the expected revision and confirm it is the next chart hop.
   Set `upgrade_context=homelab-staging` for rehearsal or
   `upgrade_context=homelab-prod` for production. Reconcile the source and
   infrastructure Kustomization.

   ```sh
   # Choose homelab-staging or homelab-prod.
   upgrade_context=homelab-staging
   flux --context "$upgrade_context" -n flux-system reconcile kustomization \
     infrastructure-controllers --with-source
   ```

4. Stop if the Kustomization's `status.lastAppliedRevision` differs from the
   expected Git revision or the live HelmRelease pin differs from the hop.
   To request immediate Helm reconciliation, run the applicable command.

   ```sh
   # CNPG hop
   flux --context "$upgrade_context" -n cnpg-system reconcile helmrelease cnpg

   # Longhorn hop
   flux --context "$upgrade_context" -n longhorn-system reconcile helmrelease longhorn
   ```

5. Check the HelmRelease's current observed generation and `Ready=True`.
   Confirm `status.history[0]` is deployed with the expected chart version.
   Verify the running controller image, targeted CRD schemas and rollout
   health before proceeding to the next hop. Save the commit and observations.
   [Flux HelmRelease](https://fluxcd.io/flux/components/helm/helmreleases/)

## 3. Rehearse the sequence on staging

**Before the first chart change**, require a ready primary, successful
application read/write, and a fresh completed CNPG backup with the required WAL
in S3 for **both Forgejo and n8n**. Stop until n8n passes the same checks as
Forgejo.

### Staging preflight checklist

Status on 2026-11-20. Recheck live health and backup freshness before the window.

- [x] Recover n8n. The app uses `n8n-db-staging-cluster-v2`, applied its schema
  migrations, and passed its readiness check. Removed two released n8n volumes
  after verifying that neither had a live claim or attachment. The original
  CNPG cluster's detached volume still has a bound claim.
- [x] Verify both active CNPG primaries and their latest base backup and WAL
  objects in S3. Forgejo repository reads also passed.
- [ ] Complete a controlled Forgejo application write and readback.
- [ ] Complete the Longhorn backup and restore checks below.
- [ ] Record `lab1`'s datastore type and off-node backup and server-token
  locations. Verify the matching recovery procedure and host access.
- [ ] Record the staging interruption window and confirm the first hop's
  staging-only chart pin and rollback point.
- [ ] Decide whether to repair or record the existing staging Forgejo runner
  and Ledgerly Flux failures as outside the rehearsal checks.

### Longhorn backup and restore checks

The staging S3 target is available. Twelve latest volume backup metadata
objects were verified in S3. Both active CNPG database volumes are covered by
their native backups. The active Forgejo repositories and n8n files have
completed Longhorn backups.

- [x] Confirmed the Forgejo runner cache is mounted as Docker's working
  storage and can be rebuilt from image pulls and builds.
- [ ] Record a verified Grafana export and recovery method, or agree that
  its staging data is disposable. The temporary Grafana S3 backup was
  removed under the retention decision for this work.
- [x] Preserved both detached Minecraft world volumes. Verified the S3
  metadata for home world backup `backup-85ae3b36c020422e` and creative world
  backup `backup-62b77d61201b4ec0` on 2026-11-20. Both volumes are detached.
- [ ] Create a one-off staging `SystemBackup` with `spec.volumeBackupPolicy`
  set to `disabled`. Wait for `Ready` and verify its bundle in the default S3 target.
  Record its name and timestamp alongside the separate volume and database
  recovery artifacts. [Longhorn system backup](https://longhorn.io/docs/1.11.1/advanced-resources/system-backup-restore/backup-longhorn-system/)
- [x] Restored `forgejo-data` from `backup-a7e24d398a6347ca` into a separate
  test volume and claim. The isolated Pod mounted it read-only and `git fsck`
  passed on both repositories. Removed the test resources afterward.
  [Longhorn volume restore](https://longhorn.io/docs/1.11.1/snapshots-and-backups/backup-and-restore/restore-from-a-backup/)

### Rehearsal sequence

Schedule a staging interruption for the single-node sequence below. Use the
rehearsal to validate charts, volume reattachment, and backups. Record
production multi-node drain and database failover as untested by this rehearsal.

1. On staging's K3s 1.32, upgrade CNPG to **1.26** and verify both staging
   databases. This CNPG step can restart Postgres even if in-place instance
   manager updates are enabled.
2. Bring staging K3s to **1.33**. This reaches the Kubernetes version where
   production starts. Production already has CNPG 1.25 on K3s 1.33, outside
   CNPG 1.25's published range. Its first operator hop is 1.26 on the existing
   Kubernetes version.
3. On **K3s 1.33**, apply CNPG **1.27**, then **1.28**. Check each release and
   database rollout before applying the next one.
4. Upgrade K3s to **1.34**. Apply CNPG **1.29**, then **1.30**, checking the
   controller, database pods and backups after each hop.
5. Upgrade K3s to **1.35**. Roll Longhorn from **1.11.1 to 1.12.2**. Verify
   the manager, CSI and all volume engines using the Longhorn checkpoint
   below. Record a test volume reattach and confirm backup target access.
6. Upgrade K3s to **1.36**. Repeat app and backup checks with the final
   combination. Record the durations and any recovery steps needed. Test the
   restore procedures in staging or with disposable infrastructure using
   nonproduction data.

Use the [CNPG version matrix](https://cloudnative-pg.io/docs/1.30/supported_releases/)
for historical compatibility, the [1.26 upgrade notes](https://cloudnative-pg.io/docs/1.26/installation_upgrade/#upgrading-to-126-from-a-previous-minor-version)
for its restart behavior, and the [Longhorn upgrade guide](https://longhorn.io/docs/1.12.2/deploy/upgrade/)
for the manager and engine steps.

**Proceed when** staging reaches the final combination, storage reattaches,
and **both Forgejo and n8n** have ready primaries, pass the application
read/write and data-retention checks, and complete fresh backups with the
necessary WAL. In the restore rehearsal, prove that the restored writer
stop state survives server and node startup. Verify storage and database
data, then reconcile Flux with the application writer hold still in place.
Confirm jobs and consumers stay stopped until the staged release. Record
the rehearsal results.
Resolve a failed staging hop before publishing production pins.

## 4. Run production in checkpoints

1. Confirm the step 1 backups, staging exit gate, and maintenance window.
   Pause unrelated changes and capture the starting output from the checks
   below. Pass the storage placement gate and move the Forgejo runner off
   `prod4` before cordoning or isolating the node. Choose the `prod4` approach
   before publishing the first production pin.

   - Prefer isolating `prod4` until the API server reaches 1.35 when its
     workloads and replicas can move. Use Longhorn replica eviction to move
     data to eligible disks while the source remains available, then use
     the agent drain checks. Verify all replicas and workloads are healthy
     elsewhere before taking the host offline. Verify detached volumes'
     replica data through a controlled attach where necessary.
     [Longhorn node and disk maintenance](https://longhorn.io/docs/1.12.2/maintenance/maintenance/)
   - If safe isolation is impractical, record explicit acceptance of the
     existing unsupported skew while the 1.35 kubelet is ahead of the 1.33
     and then 1.34 API server. Set a deadline inside the maintenance window,
     ending by API server 1.35. Cordon `prod4` to stop ordinary new workloads
     from scheduling there. Verify its existing replicas stay healthy.
     Stop on a missed deadline, API or kubelet errors, loss of planned
     replica redundancy, or application regressions. Record the recovery
     disposition for `prod4` if the server cannot reach 1.35.
     [Kubernetes version-skew policy](https://kubernetes.io/releases/version-skew-policy/#kubelet)
2. On **K3s 1.33**, move CNPG through **1.26 → 1.27 → 1.28** using the
   rehearsed chart pins. Wait for the controller and all four database clusters
   to finish each rollout. Expect applications to reconnect on primary
   switchovers and a brief Colddev database outage on restart.
3. Prepare Colddev for node maintenance, then upgrade K3s to **1.34** using
   the per-node procedure below. Apply CNPG **1.29 → 1.30** after K3s 1.34 is
   healthy. Recheck replication, connectivity and archiving after every
   operator rollout.
4. Upgrade K3s to **1.35**, then roll Longhorn to **1.12.2** using the
   rehearsed manager and volume engine procedure below. Finish that checkpoint
   before the final Kubernetes hop.
5. Upgrade K3s to **1.36**. Validate the final platform and record the last
   known-good Git revision, image versions, app checks, and fresh backups.
   After all node maintenance, restore the approved Colddev instance count
   if it was increased temporarily. Verify the retained primary, app
   reconnect and a new backup. Planner's activation is tracked separately in
   [PR #188](https://github.com/coldb/homelab/pull/188).

### For every K3s minor hop

1. Record the known-good environment Git revision for this hop. Freeze pushes
   to the shared `main` during the hop, and record the Flux Deployment replica
   counts. Scale `kustomize-controller` to zero in `flux-system` and wait for it
   to stop, then stop `helm-controller` and `source-controller` the same way.
   Verify all three have stopped. This prevents chart or Kustomization changes
   and keeps the reconciler pause in the datastore recovery point.
2. Capture a datastore recovery point with application and storage writers
   stopped using the procedure below. Schedule this interruption at the start
   of each minor hop, including production. It preserves the stopped writer
   state when the datastore is restored. Save the matching K3s version, secure
   server-token location, known-good Git revision, and per-node binary and
   service configuration. Verify access to those artifacts off the server.
3. Upgrade the server first, preserving its configuration and datastore
   settings. In production, inspect workload placement on `prod0` and
   arrange any affected workload shutdown or relocation before the restart.
   Expect an API outage while its K3s service restarts. Wait for API, server
   node, and platform checks before upgrading agents. In production, return
   workloads to service after verifying the quiesced snapshot and before
   the server upgrade. A stopped SQLite copy requires its own short API
   interruption in production. In staging, keep workloads stopped through
   the upgrade and restore them afterward.
4. Complete the node and storage checks for the hop, then use the
   source-first Flux sequence in section 5 against the frozen healthy
   revision. Release the Git freeze after Flux, workload and backup checks
   pass. If a check fails, leave the freeze in place for recovery.

[K3s server-first upgrades](https://docs.k3s.io/upgrades/manual) ·
[Longhorn node maintenance](https://longhorn.io/docs/1.12.2/maintenance/maintenance/#upgrading-kubernetes)

#### Capture a recovery point with writers stopped

1. With Flux paused, record the application and operator workloads, replica
   counts, jobs and schedules, autoscalers if present, PVCs and disk mounts.
   Gate public and internal write traffic. Finish in-flight jobs, suspend
   CronJobs, CNPG ScheduledBackups, and other job producers, including
   Longhorn recurring jobs that can attach volumes. Shut down applications
   and other volume consumers. Verify any already-created Jobs and Pods
   are stopped.
2. Before hibernating CNPG, save the writer Pod and PVC, PostgreSQL
   system identifier, WAL timeline and durable WAL position for each database
   off the cluster. On the primary, record the system identifier from
   `pg_control_system()` and the flushed LSN and its WAL filename from
   `pg_current_wal_flush_lsn()` and `pg_walfile_name()`. Refresh the record
   after primary changes during the hop and at rollback shutdown when possible.
   Record the archive coverage and intended recovery cutoff.
   [PostgreSQL WAL and control functions](https://www.postgresql.org/docs/17/functions-admin.html)

   Hibernate each CNPG Cluster with `cnpg.io/hibernation=on` and wait for the
   hibernation condition. In production, record Rocket.Chat's primary,
   replica-set name and `optimes.lastCommittedOpTime` from `replSetGetStatus`.
   Save `rs.conf().settings.replicaSetId` with that off-cluster record.
   Then set `spec.pause: true` on its `PerconaServerMongoDB` resource and wait
   for the database Pods to stop. Use the owning operator's shutdown procedure
   for any other managed writers.
   Keep the PVCs. Verify there are zero live or scheduled writer Pods and all
   affected volumes are detached, including manual attachments, before the
   backup. Record the stopped state and how to reverse it.
   [CNPG hibernation](https://cloudnative-pg.io/docs/1.26/declarative_hibernation/) ·
   [Percona pause and resume](https://docs.percona.com/percona-operator-for-mongodb/pause.html)
3. Save the datastore with the writer stop state in effect. Use the
   method for the backend confirmed in preparation.

   - **SQLite:** Stop the K3s server and confirm it has exited. Copy the
     entire `server/db/` directory under the configured K3s data directory,
     preserving permissions and any journal files with the database. Verify
     the copied files and run SQLite's `PRAGMA integrity_check` on a
     disposable copy before using the checkpoint. Restore the matching directory with K3s stopped. Keep the
     server stopped for the staging upgrade. For production, restart the
     same binary after the copy is verified so services can recover before
     the rolling upgrade.
     [K3s SQLite backup](https://docs.k3s.io/datastore/backup-restore/#backup-and-restore-with-sqlite) ·
     [SQLite copy consistency](https://www.sqlite.org/howtocorrupt.html#backup_or_restore_while_a_transaction_is_active)
   - **Embedded etcd:** Take and verify a K3s etcd snapshot.
   - **External datastore:** Take and verify a transactionally consistent
     backup with the backend's rehearsed procedure.

   Store the recovery copy off-server, with the PVC mapping, replica
   placement and current backup record. Keep the writer stop state until
   the copy is verified. For the scheduled production upgrade, reverse
   the temporary stops after backup verification and before the version
   change. Start storage-backed services before dependent applications and
   verify data before reopening traffic. Keep Flux paused until the hop
   checks pass.

#### Single-node staging outage

1. Keep the recovery-point stop state on `lab1` through the upgrade. Its
   volumes have nowhere to move and the drain policy protects their sole
   replica. Use the planned offline outage with that protection enabled.
   Keep the existing PVCs, node identity and disks.
2. Upgrade the pinned server binary. Verify the disk mounts, API, node,
   Longhorn manager and CSI. Reverse the temporary stops, starting both
   databases before their consumers. Verify data and application read/write
   on Forgejo and n8n through private checks. After the hop's Flux checks
   and new backups pass, reopen traffic.

#### Verify production storage placement before the `prod4` decision

1. All 30 production Longhorn volumes request three replicas. At inventory,
   only `prod1`, `prod2`, and `prod4` permit replica scheduling, and
   `prod4` runs 25 replicas. Longhorn blocks new replicas on cordoned nodes,
   uses hard node anti-affinity, and permits degraded volume creation.
   [Longhorn scheduling settings](https://longhorn.io/docs/1.12.2/references/settings/#scheduling)
2. Before either `prod4` path or creating the temporary Colddev PVC, prove
   three other distinct Ready, schedulable agents have eligible Longhorn
   disks, matching selectors and sufficient headroom. Include capacity for
   replica relocation and the extra Colddev volume. Both node and disk
   scheduling are currently disabled on `prod3`. Validate the reason and
   suitability of that disk before enabling it, or provision another eligible
   node. Stop if a third eligible agent cannot be established. Verify that a
   representative new test volume can get three healthy replicas outside
   `prod4`, using the same placement constraints as the intended volumes.
3. Record expected placements during each drain. For attached volumes,
   start with three healthy replicas and require at least two healthy
   replicas on other nodes throughout each drain. Restore all three before
   moving to another node. For detached volumes, verify retained replica
   placement and backup coverage before taking a disk offline. Stop if the
   required redundancy, recoverability, or application availability is lost.

#### Move the Forgejo runner before `prod4` maintenance

1. Before cordoning or isolating `prod4`, pause new runner work and finish
   active jobs. The runner selects `forgejo-runner=true` and only `prod4`
   currently has that label. Choose an eligible, compatible replacement
   agent with room for the runner and access to its Longhorn cache PVC.
2. Suspend the production `infrastructure-controllers` Kustomization while
   stopping the runner. Record its current state so reconciliation can be
   restored afterward.
   Verify the old Pod has exited and `forgejo-runner-docker-cache` is detached.
   Add the label to the replacement and remove it from `prod4` using the
   [repo's runner procedure](../README.md#forgejo-runner). Restore the
   deployment and the Kustomization's previous reconciliation state.
   Verify the cache mounts on the replacement and run a safe test job
   before allowing `prod4` maintenance. Check runner placement again
   when taking the replacement agent through later node upgrades. Repeat the
   move or include a scheduled runner-only outage and verify restart before
   moving to the next agent.

#### Colddev before the first production K3s hop

1. Colddev's sole primary is on `prod1` and its disruption budget allows zero
   evictions. After production reaches CNPG 1.28, scope a change to
   `database/production/colddev/` to temporarily set `spec.instances: 2`.
   Recheck the storage placement gate, then reconcile the `databases`
   Kustomization. Wait for the new instance to be ready and caught up on a
   different node. Verify all three PVC replicas are healthy before relying
   on it for switchover.
2. Before draining a node that hosts the primary, use the matching CNPG
   plugin to promote the caught-up instance on a different node. Specify
   the `homelab-prod` context, the `colddev` namespace, the
   `colddev-db-production-cluster-v1` Cluster and the candidate Pod. Verify
   the writer service, application reconnect, and the old primary returning
   as a replica. Update the off-cluster primary and WAL record. Check live
   PDBs and placement before each drain. Stop on a failed check or a blocked
   eviction. Keep both instances through the hops.
   [CNPG 1.28 plugin switchover](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.28.1/docs/src/kubectl-plugin.md#promote)

#### One production agent at a time

1. Before cordoning, check what runs on the node, where workloads can
   reschedule, disruption budgets, database primary and replica placement,
   and Longhorn attachments, replica locations and headroom. Plan a CNPG
   switchover if required and verify the replacement primary. Confirm each
   affected volume meets the replica floor on other eligible nodes, and the
   node's local workloads have a safe maintenance path.
2. Cordon the node after the advance placement check. Stop any automation
   that can bind new Pods directly or tolerate the cordon during maintenance.
   With the node cordoned, finish active jobs, handle manual attachments and
   run the final inventory. For every listed Pod, verify that its `emptyDir`
   contents can be discarded or have been saved. Include CNPG scratch and
   shared memory. Require a zero exit status and review every row. Stop if
   the API call or parsing fails, or if any Pod remains unreviewed.

   ```sh
   (
     set -euo pipefail
     upgrade_node=prod1  # Choose the agent being maintained.
     kubectl --context homelab-prod get pods -A \
       --field-selector "spec.nodeName=$upgrade_node" -o json |
       jq -ers '
         if length != 1 or (.[0].items | type) != "array"
         then error("Expected a Kubernetes PodList")
         else
           (["NAMESPACE", "POD", "EMPTYDIR_VOLUMES"] | @tsv),
           (.[0].items[] |
             select(all(.metadata.ownerReferences[]?; .kind != "DaemonSet")) |
             [.spec.volumes[]? | select(has("emptyDir")) | .name] as $dirs |
             select($dirs | length > 0) |
             [.metadata.namespace, .metadata.name, ($dirs | join(","))] | @tsv)
         end'
   )
   ```

3. Immediately after the post-cordon inventory passes, drain with
   `--ignore-daemonsets --delete-emptydir-data` and the rehearsed timeout.
   Repeat the inventory before retrying a drain. Stop on a blocked eviction,
   failed reattachment, or breach of the replica floor. Keep PDB eviction
   and the last-replica protection enabled. Verify reattached workloads
   are serving elsewhere before restarting K3s. Verify any documented
   runner-only outage after restart.
   [kubectl drain options](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/#options)
4. Install the pinned agent version. Wait for the expected version, `Ready`
   and healthy CSI before uncordoning. Check application reconnect, CNPG
   replication, volume reattachment and each affected volume's expected
   healthy replica count. Advance only after the node and workloads are
   healthy. Handle `prod4` under the recorded skew decision until the server
   reaches 1.35. At 1.35, align it to the rehearsed patch, verify API and
   kubelet versions and storage, then restore normal scheduling. If it was
   isolated, verify rejoining capacity and volume health before allowing
   workload placement.

#### Longhorn manager and volume engines

1. Verify the system and per-volume backups are current. Upgrade the manager
   with the environment's chart pin and wait for Flux, the manager, CSI, and
   the new engine image to be ready on applicable nodes. Automatic engine
   upgrades are disabled in both environments.
2. Upgrade V1 volume engines manually using the new default engine image.
   Live upgrade healthy volumes where supported. Use a planned detach and
   offline upgrade for other volumes and for the detached inventory. Work in
   batches and keep the previous engine image available until all volumes pass.
3. Check every volume, including detached ones, for the target `spec.image`
   and `status.currentImage`. If an offline upgrade needs an attach to verify
   its current image, attach it under controlled maintenance without writers,
   verify the engine and data, then return it to its prior attachment state.
   For each attached volume, compare `spec.numberOfReplicas` with the number of
   `RW` replicas in the active Engine's `status.replicaModeMap`. Wait for
   healthy volumes and the expected count. Verify test reattachment, live app
   mounts and backup target access before starting K3s 1.36.
   [Longhorn V1 engine upgrade](https://longhorn.io/docs/1.12.2/deploy/upgrade/upgrade-engine/)

### Read-only checkpoint commands

Use `homelab-staging` for staging or `homelab-prod` for production.
Record the observed output at each checkpoint.

```sh
upgrade_context=homelab-staging

kubectl --context "$upgrade_context" get --raw /version
kubectl --context "$upgrade_context" get nodes -o wide
flux --context "$upgrade_context" get kustomizations -A
flux --context "$upgrade_context" get helmreleases -A
kubectl --context "$upgrade_context" get clusters.postgresql.cnpg.io -A
kubectl --context "$upgrade_context" get backups.postgresql.cnpg.io -A
kubectl --context "$upgrade_context" -n longhorn-system get volumes.longhorn.io \
  -o custom-columns=NAME:.metadata.name,STATE:.status.state,HEALTH:.status.robustness,CURRENT:.status.currentImage,DESIRED:.spec.image,REPLICAS:.spec.numberOfReplicas
kubectl --context "$upgrade_context" -n longhorn-system get engines.longhorn.io \
  -o custom-columns=VOLUME:.spec.volumeName,ACTIVE:.spec.active,MODES:.status.replicaModeMap
kubectl --context "$upgrade_context" -n longhorn-system get systembackups.longhorn.io,backups.longhorn.io
kubectl --context "$upgrade_context" -n longhorn-system get volumes.longhorn.io \
  -o custom-columns=VOLUME:.metadata.name,NS:.status.kubernetesStatus.namespace,PVC:.status.kubernetesStatus.pvcName,BACKUP:.status.lastBackupAt
```

Check DNS and ingress from inside and outside the cluster. Exercise a sign-in
and a safe read/write in the affected apps. Confirm a primary and the expected
replicas are ready, WAL archiving works, and fresh backups finish for each
production database. Keep the progress record by step with the version,
Git revision, backup IDs, and observed outcome.

## 5. Stop and recover if a checkpoint fails

For a K3s minor rollback, use steps 2–6. For a failed CNPG or Longhorn chart
hop, use step 7 and the data-restore checks if needed. Both paths start with
step 1 and end with steps 8–9.

1. Stop before the next node or chart hop. Record the failure, Flux artifact
   and applied revisions, pod events, last backup, and any changes since the
   recovery point. Preserve datastore, PVC and archive data during diagnosis.
   Keep the shared `main` push freeze and Flux pause in place. For a chart
   failure in either environment, freeze `main` and stop Flux in the same
   order as for a K3s hop before trying to recover. Allow the reviewed
   environment-scoped recovery commit described below during the freeze.
2. For a K3s minor rollback, gate incoming writes outside the restored
   cluster. If the API responds, stop current writers and detach volumes
   using the checkpoint shutdown sequence. If it is unavailable, use the
   rehearsed host-access procedure to stop writers and keep traffic fenced.
   Use the datastore-specific K3s rollback procedure to stop K3s and its
   remaining pod processes on every node. Record changes since the recovery
   point and preserve the current datastore and affected disks before
   restoring.
   Restore the writer-stopped datastore with its matching K3s version and
   token. Prepare compatible agent binaries and start the server first.
   Keep the agents stopped until the restored API confirms the writer fence
   and Flux pause match the checkpoint, including operator-managed writers
   and already-bound Pods. Stop if those checks fail.
   [K3s rollback](https://docs.k3s.io/upgrades/roll-back)
3. Start compatible agents one at a time while application writers stay
   stopped. Apply the recorded `prod4` recovery disposition. Reconcile the
   restored PV and Longhorn metadata with the preserved disks before any
   application mounts. The baseline production volumes all have the Longhorn
   revision counter disabled. For each affected volume, manually establish
   replica data consistency using the rehearsed procedure and data checks.
   Verify disk mounts and CSI. Keep traffic and Flux paused.
   [Longhorn restored datastore and replica checks](https://longhorn.io/docs/1.12.2/advanced-resources/cluster-restore/rancher-cluster-restore/)
4. Before reusing PostgreSQL PVCs, verify the restored CNPG primary selection
   against the authoritative PostgreSQL timeline and WAL cutoff. Compare
   the Cluster's primary identity and PVC mapping with the off-cluster
   writer record. Inspect copies of the stopped data with matching
   PostgreSQL tools such as `pg_controldata` and archive evidence. Verify
   the system identifier, timeline history, and WAL through the agreed
   recovery point. After a switchover the old primary can be stale even
   when all of its Longhorn replicas agree. If the identity or data cannot
   be proved, keep the Cluster hibernated and use the native archive.
   For MongoDB, verify the preserved data on isolated copies. Require an
   exact match to the original `replicaSetId` and evidence of committed
   operations through the agreed recovery point before resuming on the
   original disks. Use the MongoDB-native restore path if these checks fail.
   [PostgreSQL control data](https://www.postgresql.org/docs/17/app-pgcontroldata.html) ·
   [CNPG recovery](https://cloudnative-pg.io/docs/1.28/recovery/) ·
   [MongoDB replica-set ID](https://www.mongodb.com/docs/manual/reference/replica-configuration/#mongodb-rsconf-rsconf.settings.replicaSetId)
5. Use the recovery procedure for the recorded backup type if preserved
   data fails its checks. Confirm the selected recovery point and expected
   data loss before switching any clients.

   - **PostgreSQL base backup and WAL.** Bootstrap a separate CNPG Cluster
     with new PVCs, using the verified backup ID and complete WAL chain to
     the agreed recovery target. Keep the old Cluster hibernated. Read the
     original archive and use a separate destination for new backups.
     [CNPG recovery targets](https://cloudnative-pg.io/docs/1.28/recovery/#recovery-targets)
   - **MongoDB-native backup.** Leave the original replica set paused.
     Restore into an isolated compatible Percona cluster with
     `PerconaServerMongoDBRestore`. Use `backupName` when the original
     Backup object is available to the restore operator or `backupSource`
     for the verified remote artifact. Use PITR only when the required
     oplog is available for the target.
     [Repository's MongoDB restore procedure](../database/base/rocketchat/RESTORE.md) ·
     [Percona 1.20.1 backup and restore](https://docs.percona.com/legacy-documentation/percona-operator-for-mongodb/PerconaOperatorMongoDB-1.20.1.pdf)
   - **Longhorn volume backup.** Restore to a new isolated volume and verify
     data privately. Use the rehearsed claim switch for the consumer after
     verification. For a database volume, verify database identity and
     the recovery point before opening it to clients.
     [Longhorn volume restore](https://longhorn.io/docs/1.12.2/snapshots-and-backups/backup-and-restore/restore-from-a-backup/)

6. Verify databases and storage behind the traffic gate using controlled
   maintenance probes. In staging, rehydrate the validated Forgejo and n8n
   databases or use verified replacements. In production, do the same for
   the validated CNPG databases and resume validated MongoDB and other
   managed databases. Wait for ready primaries and volumes and check data.
   Keep retired databases stopped and verify the chosen endpoints, TLS and
   credentials. Leave write-producing consumers, Jobs and schedules stopped
   through Flux reconciliation.
7. For a CNPG or Longhorn chart failure, check CRD, instance manager and
   volume-engine state before choosing a version-specific forward fix or
   restore. Longhorn prohibits downgrading after a successful upgrade.
   Before any data restore, apply the writer stop procedure from the
   recovery checkpoint and verify the fence. Follow the storage,
   backup-type and database verification steps above. If a controller
   required for the restore is unhealthy, use step 8 to reconcile only
   its reviewed recovery change while the writer hold remains in effect.
   Return to the data checks before permitting consumers to start.
   [CNPG upgrade guidance](https://cloudnative-pg.io/docs/1.30/installation_upgrade/#upgrades) ·
   [Longhorn downgrade prevention](https://longhorn.io/docs/1.12.2/deploy/upgrade/#upgrade-path-enforcement-and-downgrade-prevention)
8. Resume Flux against the verified safe environment state. Both clusters
   follow `main`. Render a recovery commit for a data restore or chart
   failure, or if `main` moved since the known-good revision.
   Include any verified replacement claims and writer endpoints. For a
   data recovery, hold writers stopped in the recovery commit as well as
   live. Use temporary environment-scoped patches for the affected
   consumers, Jobs and schedules. For Helm-managed consumers, put the hold
   in the release's values or keep the owning release suspended. Keep
   Deployments and StatefulSets scaled down and CronJobs and actual
   write-producing Jobs suspended. Keep other job producers and retired
   databases stopped. Verify the rendered hold in both environments and
   confirm it covers every writer in the recorded inventory. Keep external
   traffic gated. For a failed Helm rollout, set
   `spec.suspend: true` on the affected release in Git and live before
   allowing apply controllers to start. Verify the other environment's pins
   before publishing the scoped recovery commit. Hold `main` at the resulting
   safe revision through source and apply resumption. Bring back
   `source-controller` alone and reconcile the `flux-system` GitRepository.
   Confirm its ready artifact matches the exact safe revision. Then restore
   `kustomize-controller` and verify the root and infrastructure have
   applied that revision, with the expected chart pins live. The root can
   restore the Helm controller replicas. A failed release must therefore
   remain suspended through this check. Restore `helm-controller` if the root
   has not already done so. Verify that the live suspension survived the
   apply and that `main` still points at the expected revision. Verify the
   writer hold also remains in effect after its owning Kustomizations and
   HelmReleases reconcile. When safe, remove the failed release's suspension
   in a separate reviewed change that retains the writer hold. Confirm the
   deployment succeeds.
9. Verify storage and database data, backups, Flux convergence, and the
   live writer hold with controlled probes. Then release the hold in stages.

   - **Check schema prerequisites before starting consumers.** For Ledgerly,
     compare the chosen writer's Drizzle migration history with the migrations
     shipped in the pinned Ledgerly image. Keep the app at zero replicas if
     the schema is incompatible or while migrations are pending. If a
     migration is required, use a separate reviewed change to release only
     the migration hold and render a fresh Job name in the environment's
     `ledgerly-migrations` overlay. Use the same image digest as the app and
     confirm `ledgerly-secret` points to the chosen writer before the Job runs.
     Require `Complete=True` on that new Job and verify the updated schema
     before releasing the app. Flux can report a suspended migration Job
     healthy, so check the Job itself.
     [Ledgerly migration Job](../apps/base/ledgerly-migrations/job.yaml) ·
     [Flux Job health reader](https://github.com/fluxcd/pkg/blob/runtime/v0.110.3/runtime/statusreaders/job.go#L54-L65)
   - Restore the consumers and verify storage, endpoints and private app
     checks. Review pending and missed executions before resuming other
     write-producing Jobs and schedules.
   - Reopen public traffic, verify workloads and fresh backups, then release
     the Git freeze. Keep Planner suspended until production verification
     is recorded.
     [CronJob schedule suspension](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#schedule-suspension)
