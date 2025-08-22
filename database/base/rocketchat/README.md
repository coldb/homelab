## Bootstraping new instance

Connect to the admin database and create a new user for rocketchat.

```javascript
use rocketchat

db.createUser({
  user: "rocketchat",
  pwd: "<password>",
  roles: [
    { role: "readWrite", db: "rocketchat" }
  ]
});
```

## Connection string examples

```bash
mongosh  "mongodb://<username>:<password>@rocketchat-db-production-cluster-v1-rs0.rocketchat.svc.cluster.local/admin?replicaSet=rs0&ssl=false"
mongosh  "mongodb://<username>:<password>@rocketchat-db-production-cluster-v1-rs0.rocketchat.svc.cluster.local/rocketchat?replicaSet=rs0&ssl=false"
```
