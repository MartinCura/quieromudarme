# QuieroMudarme API

```bash
uv run python -m edgedb.codegen --dir ./quieromudarme/db/ --file ./quieromudarme/db/__init__.py
uv run ruff format ./quieromudarme/db/__init__.py
```

To link the host EdgeDB CLI with the instance running as a docker service:

```bash
edgedb -P 5656 instance link --trust-tls-cert quieromudarme-docker
```

## Deployment

```bash
./deploy/upload.sh
```

To link the EdgeDB CLI with a new prod instance (or if it changed IP) use:

```bash
export EC2_INSTANCE_ID="i-0eb8d32faac51a6f6"
export AWS_PROFILE="tincho"
source .env.production
ec2_ip=$(aws --profile ${AWS_PROFILE} ec2 describe-instances --instance-ids ${EC2_INSTANCE_ID} --query 'Reservations[*].Instances[*].PublicIpAddress' --output text)
edgedb --dsn edgedb://edgedb:${EDGEDB_PASS}@${ec2_ip}:${EDGEDB_EXT_PORT}/edgedb instance link quieromudarme-prod --non-interactive --trust-tls-cert --overwrite
# Can now run things like: `edgedb -I quieromudarme-prod migrate`
```
