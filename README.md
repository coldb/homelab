# homelab

## Setting up server

Each k3s node (server + every agent) must trust the colddev internal CA so
containerd can pull from the private Forgejo container registry. Without this,
image pulls fail with `x509: certificate signed by unknown authority`.

The same self-signed colddev CA is used for **both** the staging and production
clusters (the two SOPS-encrypted copies in
`infrastructure/controllers/{staging,production}/cert-manager/colddevnet-ca-secret.yaml`
contain identical certificate bytes). One CA file, installed into the system
trust store, covers both `forgejo-staging.colddev.net` (staging) and
`forgejo.colddev.net` (production) — containerd uses the system trust pool
when no explicit `ca_file` is configured for the registry.

Copy the certificate to server

```bash
scp /tmp/colddev-ca.crt <user>@<server-host>:/tmp/colddev-ca.crt
```

Run on **every** node in the cluster:

```bash
# Install the colddev internal CA into the system trust store.
# Same file content on both staging and production nodes.
sudo install -m 644 /path/to/colddev-ca.crt /usr/local/share/ca-certificates/colddev.crt
sudo update-ca-certificates

# Restart k3s so containerd picks up the updated trust store.
sudo systemctl restart k3s         # on the server node
sudo systemctl restart k3s-agent   # on each agent node
```

Verify the CA is trusted from the node:

```bash
# staging cluster
curl -I https://forgejo-staging.colddev.net/v2/

# production cluster
curl -I https://forgejo.colddev.net/v2/
```

Both should return an HTTP response (e.g. `401 Unauthorized` for `/v2/`
without auth) — never an `x509` error.


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


## Forgejo runner

To create the initial admin user see [infrastructure/controllers/base/forgejo/README.md](infrastructure/controllers/base/forgejo/README.md).


## Monitoring

For monitoring the [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) helm chart is used.

### Prometheus UI

To access the prometheus UI a port forward is needed to expose it on localhost. This will expose the UI at [http://localhost:8080/](http://localhost:8080).

```bash
kubectl port-forward -n monitoring pod/prometheus-kube-prometheus-stack-prometheus-0 8080:9090
```


