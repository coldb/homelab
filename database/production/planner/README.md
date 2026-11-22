# Connect to Planner from pgAdmin

After the Planner database is Ready, export the public CA certificate that
CloudNativePG generated.

```sh
kubectl --context homelab-prod -n planner get secret planner-db-ca \
  -o jsonpath='{.data.ca\.crt}' | base64 --decode > planner-db-ca.crt
```

1. In [production pgAdmin](https://pgadmin.colddev.net), open **Tools → Storage
   Manager** and upload `planner-db-ca.crt` to the top level of **My Storage**.
2. Open **Tools → Import/Export Servers**, select **Import**, and choose
   [pgadmin-server.json](pgadmin-server.json). Leave **Remove all the existing
   servers?** off and import **Planner Production** once.
3. Connect to **Planner Production** and enter the `planner_db_owner` password
   supplied in the database secrets setup.

The server profile uses `verify-full` TLS to connect to the CloudNativePG writer.
The database owner is for database-level work. The migration role owns the
Planner schema and its tables.

The import applies to the signed-in pgAdmin account. If you restore Planner to
a replacement cluster, update the saved host and upload the replacement CA.
