# Tiltfile for DataHarbor

# Build Docker image
docker_build('dataharbor-app', '.',
  live_update=[
    sync('.', '/app'),
  ]
)

# Default stack (n8n is optional — use overlay local-with-n8n or ENABLE_N8N=1)
overlay = 'deploy/k8s/overlays/local-with-n8n' if os.getenv('ENABLE_N8N') == '1' else 'deploy/k8s/overlays/local'
k8s_yaml(kustomize(overlay))

# Resource port forwards & dependencies
k8s_resource('postgres', port_forwards=5432)
k8s_resource('seaweedfs', port_forwards=['8334:8333', '9334:9333', '8888:8888'])
k8s_resource('clickhouse', port_forwards=['8123:8123', '9000:9000'])
k8s_resource('qdrant', port_forwards=['6333:6333', '6334:6334'])
k8s_resource('dagster', port_forwards=3000, resource_deps=['postgres', 'clickhouse', 'qdrant', 'seaweedfs'])

if os.getenv('ENABLE_N8N') == '1':
  k8s_resource('n8n', port_forwards=5678)
