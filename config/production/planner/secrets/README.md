# Planner application secrets

Fill these three templates and add the encrypted files to this directory's
`kustomization.yaml` alongside the existing database secrets. The `*.example.yaml`
files stay outside the Kustomization.

| Template | Value to supply |
| --- | --- |
| `planner-clerk.secret.example.yaml` | Backend secret key from the Planner Clerk production instance |
| `planner-registry.secret.example.yaml` | Forgejo username and package-read token in Docker config JSON |
| `planner-cloudflare.secret.example.yaml` | Full `<UUID>.json` credential file from the locally managed tunnel |

The registry token needs read access to the Planner package. Keep the
Cloudflare account `cert.pem` on the machine that provisions the tunnel.
Use the same tunnel UUID in `apps/production/planner/cloudflared-config.yaml`.
Kubernetes converts `stringData` to base64 when it creates the Secret.

From the homelab root, create plaintext copies in a private temporary directory:

```sh
umask 077
planner_secret_dir=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/planner-secrets.XXXXXX")
cp config/production/planner/secrets/*.secret.example.yaml "$planner_secret_dir/"
```

Fill all the placeholders in those copies. Run this block from the homelab
root to encrypt them with the production recipient from `.sops.yaml`:

```sh
(
  set -eu
  planner_secret_path=config/production/planner/secrets
  planner_encrypted_dir=$(mktemp -d "$planner_secret_dir/encrypted.XXXXXX")
  trap 'rm -r -- "$planner_encrypted_dir"' EXIT

  for template in "$planner_secret_dir"/*.secret.example.yaml; do
    name=$(basename "$template" .secret.example.yaml)
    if rg -q 'REPLACE_ME' "$template"; then
      printf 'Fill the values in %s first\n' "$template" >&2
      exit 1
    else
      planner_scan_status=$?
      if [ "$planner_scan_status" -ne 1 ]; then
        exit "$planner_scan_status"
      fi
    fi
    output="$planner_secret_path/$name.enc.yaml"
    sops --encrypt --encrypted-regex '^(data|stringData)$' \
      --filename-override "$output" "$template" > "$planner_encrypted_dir/$name.enc.yaml"
  done

  mv -- "$planner_encrypted_dir"/*.enc.yaml "$planner_secret_path/"
)
```

After successful encryption, remove the plaintext copies with
`rm -r -- "$planner_secret_dir"`. Append these entries under `resources` in
`kustomization.yaml`:

```yaml
  - planner-clerk.enc.yaml
  - planner-cloudflare.enc.yaml
  - planner-registry.enc.yaml
```

Flux decrypts them using `flux-system/sops-age`. Run
`python3 scripts/planner/check.py --ready` after filling the remaining release
inputs. After rotating a Clerk or tunnel credential, reconcile the Secret and
restart its Deployment so the process loads it.
