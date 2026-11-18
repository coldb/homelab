#!/usr/bin/env python3
"""Render and check the Planner manifests without contacting the cluster."""

import argparse
from pathlib import Path
import re
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
DIGEST = r'@sha256:[0-9a-f]{64}$'
JOB_NAME = r'planner-migrate-r[a-z0-9-]{0,43}[a-z0-9]$'
INITIAL_CLUSTER = 'planner-db'


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def read_yaml(path):
    return yaml.safe_load(path.read_text())


def encrypted_payload(secret):
    name = secret['metadata']['name']
    fields = {'data', 'stringData'} & secret.keys()
    require(len(fields) == 1, f'{name}: use exactly one Secret payload field')
    values = secret[fields.pop()]
    require(isinstance(secret.get('sops'), dict) and isinstance(values, dict) and values,
            f'{name}: SOPS-encrypt the Secret')
    require(all(isinstance(value, str) and re.fullmatch(r'ENC\[[^\r\n]+\]', value)
                for value in values.values()), f'{name}: unencrypted Secret value')
    return values


def pod_inputs(workload):
    pod = workload['spec']['template']['spec']
    container = pod['containers'][0]
    writer = next(env['value'] for env in container['env'] if env['name'] == 'PGHOST')
    ca = next(volume['secret']['secretName'] for volume in pod['volumes'] if volume['name'] == 'db-ca')
    return container['image'], writer, ca


def check_database(rendered, writer, ca):
    require(re.fullmatch(r'[a-z0-9-]+-rw\.planner\.svc\.cluster\.local', writer),
            'Use the Planner CNPG writer hostname')
    cluster_name = writer.split('.')[0].removesuffix('-rw')
    clusters = [name for kind, name in rendered if kind == 'Cluster']
    require(clusters == [cluster_name], 'The database overlay must contain only the active writer Cluster')
    spec = rendered['Cluster', cluster_name]['spec']
    expected_ca = spec.get('certificates', {}).get('serverCASecret', f'{cluster_name}-ca')
    require(ca == expected_ca, 'Use the active writer Cluster’s server CA Secret')

    schedules = [obj for (kind, _), obj in rendered.items() if kind == 'ScheduledBackup']
    require(len(schedules) == 1 and schedules[0]['spec']['cluster']['name'] == cluster_name,
            'Schedule backups for the active writer Cluster')
    schedule = schedules[0]
    require(schedule['metadata']['name'] == f'{cluster_name}-daily',
            'Use a new ScheduledBackup name for a replacement writer (<cluster>-daily)')
    require(not schedule['spec'].get('suspend'), 'The active writer’s ScheduledBackup must be enabled')

    if cluster_name != INITIAL_CLUSTER:
        bootstrap = spec.get('bootstrap', {})
        require(set(bootstrap) == {'recovery'}, 'A replacement writer must bootstrap from recovery')
        recovery = bootstrap['recovery']
        require(recovery.get('database') == 'planner' and recovery.get('owner') == 'planner_db_owner'
                and recovery.get('secret', {}).get('name') == 'planner-db-owner',
                'Set the Planner database, owner and owner Secret in the recovery stanza')
        source = next((item for item in spec.get('externalClusters', [])
                       if item['name'] == recovery.get('source')), {})
        archive = source.get('barmanObjectStore', {}).get('destinationPath', '').rstrip('/')
        destination = spec.get('backup', {}).get('barmanObjectStore', {}).get('destinationPath', '').rstrip('/')
        require(archive and destination and archive != destination,
                'Set the recovery archive and a separate replacement backup destination')
    return spec


def check(ready):
    flux_file = ROOT / 'clusters/production/planner.yaml'
    definitions = list(yaml.safe_load_all(flux_file.read_text()))
    expected_paths = {
        'planner-config': './config/production/planner',
        'planner-database': './database/production/planner',
        'planner-migrations': './apps/production/planner-migrations',
        'planner-web': './apps/production/planner',
    }
    require({item['metadata']['name']: item['spec']['path'] for item in definitions} == expected_paths,
            'Planner Flux resources must point to the four production overlays')
    rendered = {}
    for item in definitions:
        name = item['metadata']['name']
        spec = item['spec']
        require(item['metadata']['namespace'] == 'flux-system'
                and spec['sourceRef'] == {'kind': 'GitRepository', 'name': 'flux-system'},
                f'{name}: share the production root GitRepository for revision checks')
        if not ready:
            require(spec.get('suspend') is True, f'{name}: use --ready after activation')
        dependencies = spec['dependsOn']
        require({'name': 'flux-system'} in dependencies, f'{name}: require the production root on the same artifact')
        require(all('readyExpr' not in dep for dep in dependencies),
                f'{name}: dependency expressions override Flux revision checks')
        if name == 'planner-migrations':
            require(spec.get('wait') is True, 'Flux must wait for the migration Job to complete')
        if name == 'planner-web':
            require({'name': 'planner-migrations'} in dependencies, 'Web must wait for migration success')
        output = subprocess.check_output(['kubectl', 'kustomize', str(ROOT / spec['path'])], text=True)
        resources = list(yaml.safe_load_all(output))
        for resource in resources:
            if resource['kind'] == 'Secret':
                require(name == 'planner-config', f'{name}: render Planner Secrets through planner-config')
                encrypted_payload(resource)
            key = (resource['kind'], resource['metadata']['name'])
            require(key not in rendered, f'{name}: duplicate rendered resource {key}')
            rendered[key] = resource
        print(f'{name}: rendered {len(resources)} resources')

    job = next(obj for (kind, _), obj in rendered.items() if kind == 'Job')
    web = rendered['Deployment', 'planner-web']
    image, writer, ca = pod_inputs(job)
    operator = yaml.safe_load(subprocess.check_output(
        ['kubectl', 'kustomize', str(ROOT / 'apps/production/planner-operator')], text=True
    ))
    require(pod_inputs(job) == pod_inputs(web) == pod_inputs(operator),
            'Migration, web and operator must share the image, writer, and CA')
    database = check_database(rendered, writer, ca)
    secret_dir = ROOT / 'config/production/planner/secrets'
    examples = sorted(secret_dir.glob('*.secret.example.yaml'))
    included = read_yaml(secret_dir / 'kustomization.yaml')['resources']
    require(not any('example' in path for path in included), 'Secret examples must never be reconciled')
    if ready:
        require(re.fullmatch(JOB_NAME, job['metadata']['name']), 'Set a release Job name of the form planner-migrate-r1')
        require(re.search(DIGEST, image), 'Publish and set the Planner image digest')
        postgres = database['imageName']
        require(re.search(r':17\.\d+[^@]*' + DIGEST, postgres), 'Pin the CNPG PostgreSQL 17 image by patch and digest')
        tunnel = rendered['Deployment', 'planner-tunnel']
        tunnel_image = tunnel['spec']['template']['spec']['containers'][0]['image']
        require(re.search(DIGEST, tunnel_image), 'Pin the cloudflared image by digest')
        tunnel_config = read_yaml(ROOT / 'apps/production/planner/cloudflared-config.yaml')
        require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', tunnel_config['tunnel']),
                'Set the actual Cloudflare tunnel UUID')
        expected = {p.name.replace('.secret.example.yaml', '.enc.yaml'): read_yaml(p) for p in examples}
        require(set(included) == set(expected), 'List all seven populated *.enc.yaml Secrets')
        templates = {example['metadata']['name']: example for example in expected.values()}
        require(len(templates) == 7, 'Keep all seven phase 1 Secret templates')
        secrets = {name: obj for (kind, name), obj in rendered.items() if kind == 'Secret'}
        require(secrets.keys() == templates.keys(), 'planner-config must render all seven expected Secrets')
        for name, example in templates.items():
            secret = secrets[name]
            require(secret['metadata'].get('namespace') == 'planner', f'{name}: wrong Secret namespace')
            require(secret.get('type') == example['type'], f'{name}: wrong Secret type')
            require(encrypted_payload(secret).keys() == example['stringData'].keys(), f'{name}: wrong Secret keys')
    print('Planner manifest checks passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ready', action='store_true', help='check the completed activation inputs')
    check(parser.parse_args().ready)
