## Get the list of the latest restores

## 1. List available backups

```bash
kubectl get psmdb-backup -n rocketchat
```

Pick the backup you want to restore from. Taking the name of the backup.

## 2. Create a Restore Object


To restore, you create a PerconaServerMongoDBRestore resource.

```yaml
apiVersion: psmdb.percona.com/v1
kind: PerconaServerMongoDBRestore
metadata:
  name: restore-rocketchat-production-db
spec:
  clusterName: rocketchat-db-production-cluster-v1
  backupName: cron-rocketchat-db-pr-20250821192000-4r8zl
```

- clusterName: must match your MongoDB cluster CR name.
- backupName: must match the backup object you want to restore.

Update the `kustomization.yaml` file with the created manifest.
