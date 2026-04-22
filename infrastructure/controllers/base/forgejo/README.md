# Forgejo

User self-registration is disabled in `configmap.yaml`
(`FORGEJO__service__DISABLE_REGISTRATION: "true"`). On a fresh install you must
manually run the bootstrap steps below: migrate the schema, create the admin
user, and register the runner.

The forgejo pod already loads `forgejo-config`, `forgejo-configmap-secret`,
and `forgejo-db-env-secret` via `envFrom`, so `FORGEJO__*` and DB variables are
already present inside the container. Admin and runner credentials live in
separate secrets and must be exported into the exec session.

## Bootstrap commands

Pull the admin and runner credentials out of their secrets:

```sh
ADMIN_USERNAME=$(kubectl get secret -n forgejo forgejo-admin-secret \
  -o jsonpath='{.data.ADMIN_USERNAME}' | base64 -d)
ADMIN_PASSWORD=$(kubectl get secret -n forgejo forgejo-admin-secret \
  -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d)
ADMIN_EMAIL=$(kubectl get secret -n forgejo forgejo-admin-secret \
  -o jsonpath='{.data.ADMIN_EMAIL}' | base64 -d)
RUNNER_SECRET=$(kubectl get secret -n forgejo forgejo-runner-secret \
  -o jsonpath='{.data.RUNNER_SECRET}' | base64 -d)
```

### 1. Render `app.ini` from the env vars and run migrations

```sh
kubectl exec -n forgejo -it deploy/forgejo -- sh -c '
  /usr/local/bin/environment-to-ini
  forgejo migrate
'
```

### 2. Create the admin user

```sh
kubectl exec -n forgejo -it deploy/forgejo \
  --env="ADMIN_USERNAME=$ADMIN_USERNAME" \
  --env="ADMIN_PASSWORD=$ADMIN_PASSWORD" \
  --env="ADMIN_EMAIL=$ADMIN_EMAIL" \
  -- forgejo admin user create \
    --admin \
    --username "$ADMIN_USERNAME" \
    --password "$ADMIN_PASSWORD" \
    --email "$ADMIN_EMAIL" \
    --must-change-password=false
```

Safe to re-run: it will fail with `user already exists` if the admin is
already provisioned.

### 3. Register the runner

```sh
kubectl exec -n forgejo -it deploy/forgejo \
  --env="RUNNER_SECRET=$RUNNER_SECRET" \
  --env="ADMIN_USERNAME=$ADMIN_USERNAME" \
  -- forgejo forgejo-cli actions register \
    --secret "$RUNNER_SECRET" \
    --scope "$ADMIN_USERNAME" \
    --name colddev-runner \
    --labels "docker:docker://node:22-bookworm"
```

The registration lives in forgejo's Postgres DB, so the runner survives pod
restarts: its init container regenerates `.runner` from the same
`RUNNER_SECRET` on each start.
