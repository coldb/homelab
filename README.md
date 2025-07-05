# homelab

## Bootstrap flux

Setup the following ENV variables:
```
export GITHUB_TOKEN=<your-token>
export GITHUB_USER=<your-username>
```

Bootstrap flux for the homelab repositroy.
```bash
flux bootstrap github \
  --owner=$GITHUB_USER \
  --repository=homelab \
  --branch=main \
  --path=./clusters/staging \
  --personal
```
### Rotating bootstrap key

To rotate the bootstrap key the following steps are needed:

- Delete the auth secret from the cluster with `kubectl -n flux-system delete secret flux-system`
- rerun flux bootstrap with the same args as before
- flux will generate a new secret and will update the deploy key if you’re using SSH deploy keys


## Enabling secret decryption

When setting up the cluster for the first time the sops-age private key needs to be registered with the cluster.
```bash
cat <path_to_age_key> |
kubectl create secret generic sops-age \
--namespace=flux-system \
--from-file=age.agekey=/dev/stdin
```
