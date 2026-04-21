# Forgejo

## Runner bootstrap

On first startup the forgejo server pod runs a `bootstrap` init container that
creates the admin user and pre-registers the runner in forgejo's database.
Under normal circumstances nothing else is needed — the runner pod will then
build its `.runner` file from the shared `RUNNER_SECRET` and start serving
jobs.

### Manual fallback

Follow these steps only if the automatic flow did not succeed (e.g. the
init container failed, or the runner is still reporting
`unauthenticated: unregistered runner`).

```sh
SECRET=$(kubectl get secret -n forgejo forgejo-runner-secret \
  -o jsonpath='{.data.RUNNER_SECRET}' | base64 -d)

kubectl exec -n forgejo -it deploy/forgejo -- \
  forgejo forgejo-cli actions register \
    --secret "$SECRET" \
    --scope <username> \
    --name colddev-runner \
    --labels "docker:docker://node:22-bookworm"
```

Replace `<username>` with the forgejo user (or org) that should own the runner.

After registration, the runner survives pod restarts without re-running this
command: the registration lives in forgejo's Postgres DB, and the runner init
container regenerates `.runner` from the same `RUNNER_SECRET` on each start.
