import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';

const [action, ...args] = process.argv.slice(2);
if (!['serve', 'migrate', 'operator'].includes(action)) throw new Error('Invalid action');
const { PGHOST, PGUSER, PGPASSWORD } = process.env;
if (!PGUSER || !PGPASSWORD) throw new Error('Database credentials are required');
const ca = '/etc/planner-db/ca.crt';
readFileSync(ca); // Refuse to start without the mounted CNPG CA.
if (!PGHOST) throw new Error('Database writer hostname is required');
const url = new URL('postgresql://localhost:5432/planner');
url.hostname = PGHOST;
url.username = encodeURIComponent(PGUSER);
url.password = encodeURIComponent(PGPASSWORD);
url.searchParams.set('sslmode', 'verify-full');
url.searchParams.set('sslrootcert', ca);
const env = { ...process.env };
delete env.PGHOST;
delete env.PGUSER;
delete env.PGPASSWORD;
delete env.DATABASE_URL;
delete env.MIGRATION_DATABASE_URL;
env[action === 'migrate' ? 'MIGRATION_DATABASE_URL' : 'DATABASE_URL'] = url.href;

if (action === 'migrate') {
  // Import from the application's working directory to resolve its dependencies.
  // The application runner holds its own session advisory lock for migration SQL.
  const { default: pg } = await import('/app/apps/web/node_modules/pg/lib/index.js');
  const client = new pg.Client({ connectionString: url.href });
  await client.connect();
  try {
    await client.query('SELECT pg_advisory_lock(73192409)');
    const child = spawn('./node_modules/.bin/tsx', ['src/platform/migrate.ts'], { env, stdio: 'inherit' });
    const code = await new Promise((resolve, reject) => {
      child.on('error', reject);
      child.on('exit', (code, signal) => resolve(signal ? 1 : code ?? 1));
    });
    if (code !== 0) process.exitCode = code;
    else {
      // Planner's reviewed migration sets the runtime grants. Deleting identities
      // or editing lists is outside the deployed MVP.
      await client.query(`
        REVOKE DELETE ON TABLE planner.users FROM planner_api;
        REVOKE UPDATE, DELETE ON TABLE planner.todo_lists FROM planner_api;
      `);
      const result = await client.query("SELECT generation FROM planner.datasets WHERE key = 'todo'");
      if (result.rows[0]?.generation !== 'todo-1') throw new Error('Unexpected dataset generation');
      console.log('planner_migration_complete: todo-1');
    }
  } finally {
    await client.end();
  }
} else {
  const command = action === 'serve' ? process.execPath : './node_modules/.bin/tsx';
  const commandArgs = action === 'serve' ? ['.output/server/index.mjs'] : ['src/platform/operator.ts', ...args];
  const child = spawn(command, commandArgs, { env, stdio: 'inherit' });
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
  child.on('error', () => { console.error('planner_process_start_failed'); process.exitCode = 1; });
  child.on('exit', (code, signal) => { process.exitCode = signal ? 1 : code ?? 1; });
}
