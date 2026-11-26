# Operate Media Manager in the homelab

The Media Manager release workflow publishes both SHA-tagged images to the
production Forgejo registry. Staging Flux reads the latest complete OCI release
and updates both staging workloads using one accepted release tuple. Production
uses a Main App digest promoted explicitly in this repository. The production
Library Agent runs separately on Synology.

## Staging prerequisites

1. Verify the first release is present at
   `forgejo.colddev.net/coldb/media-manager-staging-release` after the Media
   Manager publication workflow runs. Verify branch protection on Media
   Manager's `master` denies force pushes and deletion.
2. Configure distinct Tailscale operator identities. For staging, configure
   operator tag `tag:media-manager-operator-staging` as owner of the Ingress
   tag `tag:media-manager-staging`. Use the equivalent `-production` tags
   for production. Create a separate OAuth client in each environment
   with its corresponding operator tag and Devices Core and Auth Keys write
   scopes. Tailscale's Helm chart expects `client_id` and `client_secret` in
   Secret `media-manager-tailscale-oauth` in namespace `tailscale`. Its
   HelmRelease waits for the operator before the app is exposed.
3. Add environment-specific SOPS-encrypted Secrets with the names below.
   Add each encrypted file to the `kustomization.yaml` resources in the
   listed directory. The SOPS policy selects the staging or production age
   recipient by the directory name. Verify the registry server in each
   Docker configuration is `forgejo.colddev.net`, including in staging.

| Secret | Namespace | Relevant keys or type | Git directory |
|---|---|---|---|
| `media-manager-tailscale-oauth` | `tailscale` | `client_id`, `client_secret` | `config/<environment>/media-manager` |
| `docker-registry-auth` | `media-manager` | `kubernetes.io/dockerconfigjson` | `config/<environment>/media-manager` |
| `media-manager-release-registry` | `flux-system` | `kubernetes.io/dockerconfigjson`, read-only package access | `config/staging/media-manager-release` |
| `media-manager-agent` | `media-manager` | `token`, added after staging setup | `config/staging/media-manager` |
| `aws-backup-credentials` | `media-manager` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, production only | `config/production/media-manager` |

CloudNativePG creates the `media-manager-db-app` owner credentials and
`media-manager-db-ca` CA Secret. The two Main App roles and migration init
container use its same-namespace RW URI and validate the CA and service name.
The app does not require a manually populated PostgreSQL Secret.

## First login and staging Agent

Before exposing a new Main App, grant only the bootstrap operator TCP 443
access to its Ingress tag. Review both Tailscale grants and legacy ACLs for any
overlapping allow rule. Confirm the operator can access the endpoint and an
unintended tailnet member cannot. The operator creates the first Admin through
Initial Admin Setup and verifies sign-in. After that, enable the intended
users' grants and confirm Initial Admin Setup is closed.

The staging web endpoint is
`https://media-manager-staging.tail322116.ts.net`. The Catalog Owner creates
the staging Media Catalog and Library Agent in the app. Save the issued token
in the staging SOPS Secret and set `replicas: 1` in
`apps/staging/media-manager/agent.yaml` through Git. This starts the Agent with
separate writable synthetic media and retained state. To rotate the token,
update the encrypted Secret and change an Agent Pod-template annotation in
the same Git change to recreate the Agent and reload the environment.

Verify that Flux reports the expected release, PostgreSQL migrations succeeded,
the Agent connects to its matching Gateway, and sign-in works from the tailnet.
Check the Library Explorer WebSocket, inventory of the fixture Input Base Path,
a preview including a seek or byte-range response, and an original download.
Restart or upgrade staging and verify the fixture and Agent State survive.
Check off-tailnet reachability. If browser WebSocket or CSRF origin verification
fails, capture the `Host` and HTTPS scheme at the Main App and troubleshoot
the Tailscale proxy before widening access.

## Inspect or pin staging

The `media-manager-staging-release` ConfigMap records the monotonic sequence,
commit SHA and two verified image digests. The parent
`media-manager-staging-release-input` reconciler copies one tuple into
`media-manager-staging-app`; use its spec and Deployment annotations to see
what was prepared for rollout. A rejected artifact leaves the last valid tuple
available. Inspect the release policy and Flux events before publishing a
corrected, newer release.

For an intentional, schema-compatible rollback, submit a reviewed Git change
to `config/staging/media-manager-release-input/staging-app.yaml`. Replace all
four inline values in `spec.postBuild.substitute` with one earlier verified
release's `RELEASE_TAG`, `GATEWAY_SERVICE` (`mm-gw-<source SHA>`) and two
digest strings. The OCI reconciler continues recording newer accepted tuples.
Revert the Git pin to resume automatic rollout. Rejected releases cannot
prevent the parent from applying a valid pin.

## Activate and upgrade production

1. Verify staging with the chosen Main App image. Prepare the production
   Tailscale credentials, grants and package pull Secret with the same
   names as above in the production directories. Provision the Barman S3
   destination and scoped backup credentials. The prepared default is
   `s3://production-backup-media-manager-db/v1`; update the production overlay
   if the operator owns a different destination.
2. Set private LAN DNS for `media-manager-agents.colddev.net` to the
   production Traefik ingress address. Keep that router on the LAN, with
   public DNS-01 certificate issuance through the existing
   `letsencrypt-prod` issuer. The Gateway Ingress routes only WSS/HTTPS on
   Traefik's `websecure` entrypoint to port 4001. The web Service is exposed
   separately through Tailscale.
3. Copy `config/production/media-manager-activation/media-manager.yaml` to
   `clusters/production/media-manager.yaml` and replace the
   production `MAIN_DIGEST` value with the chosen `sha256:...` string.
   Review and merge this configuration separately from staging.
   For future promotions, update only that production digest in Git.
   Verify that the migration init container exited successfully before the
   web and Gateway containers came up.
4. Open `https://media-manager.tail322116.ts.net`. Complete production first
   login with the same restricted bootstrap process. The Catalog Owner
   issues the production Library Agent token. Independently install or upgrade
   the Synology project using the matching Agent manifest digest when ready.
   Verify private DNS and TLS from the actual NAS container, the authenticated
   WSS connection and preserved mounts. Repeat the browser WebSocket, preview
   seek, and original download checks using a NAS-backed file. Verify that
   off-LAN and off-tailnet users cannot reach the corresponding endpoints.

Before upgrading an existing production database, record the current release
and a recoverable PostgreSQL backup. With `kubectl cnpg status media-manager-db
-n media-manager`, check the last completed backup and WAL archiving. Document
a restore point and check the archive before advancing the production digest.
Keep the retained image PVC and back up any irreplaceable historical previews
separately. A schema-compatible rollback changes the production digest in Git
after confirming the schema is compatible. Otherwise prefer a fixed forward
release or restore a new CloudNativePG cluster from the selected Barman
recovery point, then change the application DB reference and CA together.
Record data loss and downtime expected for the selected restore. Keep the old
database and retained assets until verification passes. Before rolling back the
Synology Agent, confirm its SQLite schema compatibility or restore a matching
Agent State backup. Retain its media and claim files.
