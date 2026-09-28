# Deployment

Three ways to run SentinelAI, from simplest to most production-like. All of them run fully
offline in heuristic mode; Claude and LangSmith switch on only when their keys are set.

## 1. Docker Compose (local)

Prerequisites: Docker Desktop, and a `.env` with API keys (copy `.env.example`, then run
`python -m auth.api_keys operator` and `python -m auth.api_keys admin` and put the two
`config:` lines in `API_KEYS`).

```bash
docker compose up --build
```

Start order: Elasticsearch becomes healthy, the `ingest` job builds the search index and
exits, then the API starts on http://localhost:8000 (docs at `/docs`).

The first build takes several minutes: it installs CPU-only PyTorch and bakes the MiniLM
embedding model into the image, so containers start without network access. Images are
about 2.4 GB, mostly PyTorch.

| Command | What it adds |
|---|---|
| `docker compose --profile observability up` | Prometheus on http://localhost:9090, scraping `/metrics` |
| `docker compose --profile kibana up` | Kibana on http://localhost:5601 |
| `docker compose run --rm ingest python -m evals.benchmark` | Runs the benchmark inside the stack |
| `docker compose down` | Stops everything; data volumes are kept |
| `docker compose down -v` | Stops everything and deletes the index and the database |

### The search index keeps itself current

The index stores a signature: the document format version, the embedding model and the
vector size. The `ingest` job compares it on every start and rebuilds only when something
changed, so an index built by an older version, or with a different model, can never be
used by mistake. Bump `INDEX_FORMAT_VERSION` in `retrieval/indexing.py` whenever the indexed
documents change.

## 2. Kubernetes

Manifests are in `k8s/`. Elasticsearch is not included: point `ELASTICSEARCH_URL` in
`k8s/configmap.yaml` at an existing cluster (ECK, Elastic Cloud, or your own).

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n sentinel create secret generic sentinel-secrets \
  --from-literal=API_KEYS='operator:<sha256>,admin:<sha256>' \
  --from-literal=ANTHROPIC_API_KEY='' \
  --from-literal=LANGSMITH_API_KEY=''
kubectl apply -f k8s/configmap.yaml -f k8s/api-pvc.yaml
kubectl apply -f k8s/ingest-job.yaml
kubectl -n sentinel wait --for=condition=complete job/sentinel-ingest --timeout=10m
kubectl apply -f k8s/api-deployment.yaml -f k8s/api-service.yaml
```

Images are referenced as `sentinel-ai-api:0.1.0` and `sentinel-ai-worker:0.1.0`. For kind or
minikube, build them with those tags and load them into the cluster; otherwise push to a
registry and change the image fields.

What the manifests enforce:

- Startup, readiness and liveness probes on `/health`. The startup probe allows for model
  loading, so the liveness probe can stay strict.
- CPU and memory requests and limits sized for the embedding model.
- Non-root user, read-only root filesystem, no privilege escalation, all capabilities
  dropped. The app writes only to `/data` (a persistent volume) and `/tmp`.
- Credentials only in a Secret created from the command line; `secrets.example.yaml`
  documents its shape with placeholder values.
- One replica with the `Recreate` strategy (see limitations).

## 3. AWS with Terraform (plan only)

`terraform/` describes an ECS Fargate deployment: a VPC with public and private subnets,
one NAT gateway, an application load balancer (HTTPS when a certificate is given), ECR
repositories, a CloudWatch log group, an S3 bucket for benchmark reports, a Secrets
Manager secret, and least-privilege IAM roles. Tasks run in private subnets and accept
traffic only from the load balancer.

Nothing here needs to be applied to review or validate it:

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set elasticsearch_url
terraform init
terraform validate
terraform plan        # needs AWS credentials to read the account; creates nothing
```

Applying it creates billable resources (the NAT gateway and load balancer run
continuously). If you do apply it, set the secret value outside Terraform so it never
lands in state:

```bash
aws secretsmanager put-secret-value --secret-id <app_secret_arn> \
  --secret-string '{"API_KEYS":"operator:<sha256>,admin:<sha256>","ANTHROPIC_API_KEY":"","LANGSMITH_API_KEY":""}'
```

Then push both images to the ECR repositories in the outputs and run the index job with
the `run_ingest_command` output.

Elasticsearch is external here too (`elasticsearch_url`, for example Elastic Cloud). Amazon
OpenSearch is not a drop-in replacement: the Elasticsearch 8 client checks the server
product and refuses to talk to OpenSearch, so the stack does not create one.

## CI

GitHub Actions runs on every push and pull request to `main`:

| Workflow | Checks |
|---|---|
| `lint` | ruff lint and format, mypy strict, `terraform fmt` and `validate`, kubeconform on `k8s/` |
| `test` | full pytest suite against a real Elasticsearch service container, failing below 80% coverage |
| `docker` | builds both images (no push) with layer caching |

## Limitations

- **Single writer.** The API keeps incidents, runs, approvals and paused-run checkpoints in
  SQLite, so exactly one API process may run against a database. Kubernetes uses one
  replica with `Recreate`, and ECS runs one task. Scaling out means moving that state to
  PostgreSQL (LangGraph has a PostgreSQL checkpointer), not sharing the SQLite file.
- **Ephemeral state on Fargate.** Task storage is lost when a task is replaced, so runs and
  approvals reset on ECS until the PostgreSQL move. Kubernetes keeps them on a persistent
  volume.
- **Interrupted runs.** On startup, runs left queued or running by a previous process are
  marked failed with `interrupted`; runs paused for approval resume normally.
- **Local Elasticsearch has security off.** The Compose file is for local use only.
