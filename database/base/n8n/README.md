# Restoring the n8n production database

This guide covers restoring `n8n-db-production-cluster-v1` from its S3 backup (bucket `production-backup-n8n-db`). Use it for disaster recovery, migrating to a new storage class, or rebuilding the cluster from scratch.

Restore works by deleting the existing `Cluster` resource and letting CNPG recreate it, bootstrapping from the `externalClusters[0]` S3 source declared in `database.yaml`.

---

## Key facts

- **Backups live in S3** at `s3://production-backup-n8n-db/<vN>/n8n-db-production-cluster-v1/`. The current version suffix is whatever `spec.backup.barmanObjectStore.destinationPath` in `database.yaml` points to.
- **Scheduled backups** run daily at 02:00 UTC (`scheduled-backup.yaml`, 14-day retention).
- **`backups` is an ambiguous CRD short name** on this cluster — Longhorn also registers `backups`. Always use the fully-qualified `backups.postgresql.cnpg.io`.
- **CNPG `Backup` is not a `CronJob`**, so `kubectl create job --from=scheduledbackup/...` doesn't work. Trigger on-demand backups by applying a `Backup` resource (see Step 3).
- **The new cluster's backup destination must be an empty S3 path.** If it already contains WALs for this server name, CNPG aborts with `Expected empty archive`. That's why every restore bumps `destinationPath` to `/vN+1` and points `externalClusters[0].destinationPath` at the previous `/vN` where the last backup lives.

---

## Steps

### 1. Verify the backup is healthy

```sh
kubectl -n n8n get backups.postgresql.cnpg.io
kubectl -n n8n get cluster n8n-db-production-cluster-v1 \
  -o jsonpath='{.status.lastSuccessfulBackup}{"\n"}'
```

Confirm there is a recent `completed` backup. If not, fix backups first — do not proceed.

### 2. Suspend Flux and scale down n8n

```sh
flux suspend kustomization apps
flux suspend kustomization databases
kubectl -n n8n scale deploy n8n --replicas=0
kubectl -n n8n get pods -l app=n8n   # wait until none
```

Scaling down prevents writes that won't make it into the pre-restore backup.

### 3. Trigger a fresh pre-restore backup

```sh
cat <<'EOF' | kubectl apply -f -
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: n8n-db-backup-pre-restore
  namespace: n8n
spec:
  cluster:
    name: n8n-db-production-cluster-v1
  method: barmanObjectStore
EOF

kubectl -n n8n get backups.postgresql.cnpg.io -w
```

Wait for phase `completed`.

### 4. Force a WAL switch and confirm archive catches up

**Critical.** CNPG marks a backup `completed` as soon as `pg_backup_stop` returns, but the WAL file containing its stop LSN may still be sitting in `pg_wal/` on the primary, un-archived. If you delete the cluster before that WAL lands in S3, the "completed" backup becomes unrestorable with `FATAL: WAL ends before end of online backup`.

```sh
PRIMARY=$(kubectl -n n8n get cluster n8n-db-production-cluster-v1 \
  -o jsonpath='{.status.currentPrimary}')
kubectl -n n8n exec -it "$PRIMARY" -c postgres -- \
  psql -U postgres -c "SELECT pg_switch_wal();"

# Compare — lastArchivedWAL must be >= backup's endWal
kubectl -n n8n get cluster n8n-db-production-cluster-v1 \
  -o jsonpath='lastArchivedWAL: {.status.lastArchivedWAL}{"\n"}'
kubectl -n n8n get backups.postgresql.cnpg.io n8n-db-backup-pre-restore \
  -o jsonpath='endWal:          {.status.endWal}{"\n"}'
```

Do not continue until `lastArchivedWAL >= endWal`.

### 5. Delete the cluster

```sh
kubectl -n n8n delete cluster n8n-db-production-cluster-v1
kubectl -n n8n get pods,pvc -l cnpg.io/cluster=n8n-db-production-cluster-v1
```

Wait until all pods and PVCs are gone.

> If the PVCs were on a `Retain` storage class, the underlying PVs will remain as `Released`. Clean them up after the restore succeeds:
> ```sh
> kubectl get pv | grep n8n-db-production-cluster
> kubectl delete pv <released-pv-names>
> ```

### 6. Bump S3 paths in `database.yaml`

Edit `database/base/n8n/database.yaml`:

- `spec.backup.barmanObjectStore.destinationPath` → bump to the next empty path, `s3://production-backup-n8n-db/v<N+1>`.
- `spec.externalClusters[0].barmanObjectStore.destinationPath` → point at the *current* path, `s3://production-backup-n8n-db/v<N>` (where the pre-restore backup from Step 3 lives).
- `spec.externalClusters[0].barmanObjectStore.serverName` must equal `n8n-db-production-cluster-v1`.

The two comments already in `database.yaml` call this out.

### 7. Commit, push, and resume Flux

```sh
git add database/base/n8n/database.yaml
git commit -m "chore: restore n8n production database from backup"
git push
flux resume kustomization databases
```

CNPG will create a new `Cluster`, provision PVCs, and bootstrap from the S3 source. For a 3-instance cluster, replicas are built from the primary after the primary finishes recovery.

### 8. Watch the recovery

```sh
kubectl -n n8n get cluster n8n-db-production-cluster-v1 -w
kubectl -n n8n get pods,pvc -l cnpg.io/cluster=n8n-db-production-cluster-v1
kubectl -n n8n logs -l cnpg.io/jobRole=full-recovery --tail=100 -f
```

The `full-recovery` job will run, complete, and CNPG will then start the primary pod.

### 9. Resume apps and verify

```sh
flux resume kustomization apps
kubectl -n n8n get pods -w
```

Verify in the browser that n8n loads and workflows execute correctly. Then final checks:

```sh
kubectl -n n8n get pvc -l cnpg.io/cluster=n8n-db-production-cluster-v1
kubectl -n n8n get cluster n8n-db-production-cluster-v1
kubectl -n n8n get pods -l cnpg.io/cluster=n8n-db-production-cluster-v1
```

Confirm:
- All 3 PVCs are `Bound`.
- Cluster is `Cluster in healthy state` with 3 `Ready` instances.
- n8n is running and accessible.

---

## Troubleshooting

### `Expected empty archive`

The backup destination isn't empty. You skipped the path bump in Step 6 — point `destinationPath` at a fresh `/vN+1` path.

### `FATAL: WAL ends before end of online backup`

The selected base backup's stop-LSN WAL is missing from S3, so the restore can't complete. The Step 4 WAL switch is designed to prevent this; if you hit it anyway, fall back to an earlier backup.

**1. List available backups:**

```sh
kubectl -n n8n run barman-list --restart=Never \
  --image=ghcr.io/cloudnative-pg/postgresql:17.2 \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "barman-list",
        "image": "ghcr.io/cloudnative-pg/postgresql:17.2",
        "command": ["barman-cloud-backup-list","--cloud-provider","aws-s3",
                    "s3://production-backup-n8n-db/v<N>","n8n-db-production-cluster-v1"],
        "envFrom": [{"secretRef":{"name":"aws-backup-credentials"}}]
      }]
    }
  }' -- dummy
sleep 8
kubectl -n n8n logs barman-list
kubectl -n n8n delete pod barman-list
```

Replace `v<N>` with the source path from `externalClusters[0].destinationPath`. Pick the most recent backup ID *before* the broken one.

**2. Pin the restore to that backup** — add a `recoveryTarget` patch to `database/production/n8n/kustomization.yaml`:

```yaml
patches:
  - target:
      kind: Cluster
      name: n8n-db-production-cluster-v1
    patch: |-
      - op: add
        path: /spec/bootstrap/recovery/recoveryTarget
        value:
          backupID: "20260416T020001"   # ← chosen backup ID
          targetImmediate: true
```

`targetImmediate: true` stops recovery as soon as the backup reaches consistency — no WAL replay, no risk of hitting the same gap.

**3. Reapply:**

```sh
flux suspend kustomization databases
kubectl -n n8n delete cluster n8n-db-production-cluster-v1
git add database/production/n8n/kustomization.yaml
git commit -m "chore: pin n8n production recovery to earlier backup"
git push
flux resume kustomization databases
```

**4. After the cluster is healthy**, remove the `recoveryTarget` patch (bootstrap is ignored on existing clusters, but keeping dead migration config in git is noise).

### Recovery job keeps retrying with no visible progress

```sh
kubectl -n n8n logs -l cnpg.io/jobRole=full-recovery --tail=200 --all-containers
kubectl -n cnpg-system logs -l app.kubernetes.io/name=cloudnative-pg --tail=200 | grep -i n8n
```

Job has `backoffLimit: 6`. If it exhausts retries, delete the job (and cluster if needed) and restart after fixing the underlying cause.
