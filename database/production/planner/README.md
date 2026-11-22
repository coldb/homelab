# Connect to Planner from pgAdmin

After the Planner database is Ready, export the public CA certificate that
CloudNativePG generated.

```sh
kubectl --context homelab-prod -n planner get secret planner-db-ca \
  -o jsonpath='{.data.ca\.crt}' | base64 --decode > planner-db-ca.crt
```

1. In [production pgAdmin](https://pgadmin.colddev.net), open **Tools → Storage
   Manager** and upload `planner-db-ca.crt` to the top level of **My Storage**.
2. Save the JSON under [Server profile](#server-profile) as `pgadmin-server.json`.
   Open **Tools → Import/Export Servers**, choose **Import**, and select the file.
   Leave **Remove all the existing servers?** off and import **Planner Production**.
3. Connect to **Planner Production** and enter the `planner_db_owner` password
   supplied in the database secrets setup.

The server profile uses `verify-full` TLS to connect to the CloudNativePG writer.
The database owner is for database-level work. The migration role owns the
Planner schema and its tables.

The import applies to the signed-in pgAdmin account. If you restore Planner to
a replacement cluster, update the saved host and upload the replacement CA.

## Server profile

```json
{
  "Servers": {
    "1": {
      "Name": "Planner Production",
      "Group": "Servers",
      "Host": "planner-db-rw.planner.svc.cluster.local",
      "Port": 5432,
      "MaintenanceDB": "planner",
      "Username": "planner_db_owner",
      "ConnectionParameters": {
        "sslmode": "verify-full",
        "sslrootcert": "planner-db-ca.crt"
      }
    }
  }
}
```
