# Forgejo

User self-registration is disabled in `configmap.yaml`
(`FORGEJO__service__DISABLE_REGISTRATION: "true"`). On a fresh install you must
manually create the admin user and register the runner. Schema migrations run
automatically when the `forgejo web` entrypoint starts, so no manual migrate
step is required.

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

### 1. Create the admin user

```sh
 kubectl exec -n forgejo -i deploy/forgejo -- env \
  ADMIN_USERNAME="$ADMIN_USERNAME" \
  ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  ADMIN_EMAIL="$ADMIN_EMAIL" \
  forgejo admin user create \
    --admin \
    --username "$ADMIN_USERNAME" \
    --password "$ADMIN_PASSWORD" \
    --email "$ADMIN_EMAIL" \
    --must-change-password=false
```

Safe to re-run: it will fail with `user already exists` if the admin is
already provisioned.

### 2. Register the runner

```sh
 kubectl exec -n forgejo -i deploy/forgejo -- env \
  RUNNER_SECRET="$RUNNER_SECRET" \
  ADMIN_USERNAME="$ADMIN_USERNAME" \
  forgejo forgejo-cli actions register \
    --secret "$RUNNER_SECRET" \
    --scope "$ADMIN_USERNAME" \
    --name colddev-runner \
    --labels "docker:docker://node:22-bookworm"
```

The registration lives in forgejo's Postgres DB, so the runner survives pod
restarts: its init container regenerates `.runner` from the same
`RUNNER_SECRET` on each start.

### 3. Set SSH public key

In Settings > SSH / GPG Keys > Add key. The key can be found in the personal setup data.

### 4. Create access token

Access tokens are needed for access to different applications. Settings > Applications > Access tokens > New access token

#### 4.1 Registry access

Create new token with read/write access to package. Enable it for all packages public and private.


