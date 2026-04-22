# Forgejo

The server is deployed via the upstream [forgejo-helm](https://code.forgejo.org/forgejo-helm)
chart (`release.yaml`). The actions runner is deployed from raw manifests under
`runner/`.

Sensitive config (DB host/creds, server domain, root URL) lives in SOPS-encrypted
secrets in each overlay and is merged into `app.ini` via the chart's
`gitea.additionalConfigFromEnvs` — `environment-to-ini` reads any env var named
`FORGEJO__section__KEY` on container start.

## Runner registration

The chart's `gitea.actions.provisioning.enabled: true` flag generates a
registration token at install time and writes it to a Kubernetes Secret.
The runner Deployment's `register-runner` init container reads that token
and calls `forgejo-runner register` to produce `.runner`, which is persisted
to a PVC and reused across pod restarts.

Confirm the secret the chart created and adjust `runner/deployment.yaml` if
the name/key differs from `forgejo-actions-general-runner-secret` / `token`:

```sh
kubectl get secret -n forgejo | grep -i actions
```

To re-register (new token, fresh `.runner`):

```sh
# 1. Delete the chart-generated token secret so the provisioning job re-runs
kubectl delete secret -n forgejo forgejo-actions-general-runner-secret
# 2. Wipe the runner's registration file and restart
kubectl exec -n forgejo deploy/forgejo-runner -c runner -- rm -f /data/.runner
kubectl rollout restart -n forgejo deploy/forgejo-runner
```

## Admin bootstrap on a fresh install

The chart's init does not create the admin user. On a first-time install run
this once, using the credentials from `forgejo-admin-secret` (staging only —
production is already bootstrapped):

```sh
ADMIN_USERNAME=$(kubectl get secret -n forgejo forgejo-admin-secret \
  -o jsonpath='{.data.ADMIN_USERNAME}' | base64 -d)
ADMIN_PASSWORD=$(kubectl get secret -n forgejo forgejo-admin-secret \
  -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d)
ADMIN_EMAIL=$(kubectl get secret -n forgejo forgejo-admin-secret \
  -o jsonpath='{.data.ADMIN_EMAIL}' | base64 -d)

kubectl exec -n forgejo -it deploy/forgejo -- \
  forgejo admin user create \
    --admin \
    --username "$ADMIN_USERNAME" \
    --password "$ADMIN_PASSWORD" \
    --email "$ADMIN_EMAIL" \
    --must-change-password=false
```
