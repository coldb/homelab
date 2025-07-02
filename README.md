# homelab

## Enabling secret decryption

When setting up the cluster for the first time the sops-age private key needs to be registered with the cluster.
```bash
cat <path_to_age_key> |
kubectl create secret generic sops-age \
--namespace=flux-system \
--from-file=age.agekey=/dev/stdin
```
