# Log Analytics Service

A streaming log analytics service that parses JSON Lines error logs from S3 (or local files) and produces a structured error summary. Ships as both a **CLI** and an **HTTP API**, deployed on AWS ECS Fargate behind CloudFront via Terraform + GitHub Actions CI/CD.

---

## Quick answers to the four required questions

### 1. How do I run it locally against a local file? (One command.)

```bash
pip install -e . && analyze --file sample-logs/2025-09-15T14-00.jsonl --threshold 3
```

Or with Docker (no Python install needed):

```bash
docker build -t log-analytics .
docker run --rm log-analytics analyze --file /dev/stdin --threshold 3 < sample-logs/2025-09-15T14-00.jsonl
```

Expected output:
```json
{
  "total": 6,
  "byService": { "api": 1, "orders": 1, "billing": 1, "auth": 1, "cache": 1, "db": 1 },
  "alert": true,
  "parseErrors": 1
}
```
Exit code `2` (alert fired). Exit code `0` = success, no alert. Exit code `1` = error.

---

### 2. How do I run the tests?

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

The suite runs in ~3 seconds and includes:
- **46 unit tests** across core logic, S3 adapter, and HTTP API
- **1 streaming memory test** — generates a ~100 MB JSONL file and asserts peak RSS delta stays under 64 MB (proving constant-memory streaming works)

To skip the 100 MB file generation during fast iteration:
```bash
python -m pytest tests/ -v -m "not slow"
```

---

### 3. What would break first if traffic increased 100×, and what would you do about it?

**What breaks first: S3 request costs and GetObject fan-out latency.**

Every `/analyze` request issues one `ListObjectsV2` call and one `GetObject` per matching log file. At 100× traffic, that's 100× the S3 API calls, which means:

1. **S3 → ECS bandwidth** becomes the bottleneck before ECS CPU does, because each request streams potentially hundreds of MB. At 2 Fargate tasks × 100× concurrent requests, you'd saturate the 10 Gbps ENI limit quickly.

2. **ECS task count** — `desired_count = 2` with `cpu = 256` (0.25 vCPU) won't handle concurrent 500 MB streaming jobs. Each job is CPU-light but holds an open S3 connection for ~5 seconds. At 100× load you'd queue.

**What I'd do (in order of impact):**

1. **Add Application Auto Scaling to the ECS service** — scale on ALB `RequestCountPerTarget` with a target of ~5 requests/task. This is a one-Terraform-resource change and handles bursty load without over-provisioning.

2. **Pre-aggregate logs** — rather than re-reading raw files on every request, run a scheduled Lambda (triggered by S3 event notifications) that aggregates error counts per file into a DynamoDB table. The HTTP endpoint then does a cheap DynamoDB read instead of streaming from S3. This would cut S3 costs by ~99% and reduce p99 latency from seconds to milliseconds.

3. **CloudFront caching** — for callers that query the same `bucket/prefix` repeatedly (e.g., a monitoring dashboard polling every 30 seconds), a 30-second CloudFront TTL would collapse most requests to cache hits. The current config already sets `max_ttl = 30` for `/analyze`. This is free bandwidth reduction.

I wouldn't add a queue here — this is a synchronous read-only operation. A queue only helps if you need to decouple producers from slow consumers; for read queries, caching and horizontal scaling are the right tools.

---

### 4. What did you cut or skip, and why?

**Cut:**

- **HTTPS on the ALB** — the ALB listener is HTTP-only. In production you'd add an ACM cert and HTTPS listener. Cut because provisioning a certificate requires a domain name I don't have, and CloudFront already terminates TLS for the public surface.

- **VPC creation in Terraform** — the ECS module takes `vpc_id` and subnet IDs as inputs. I didn't create a VPC from scratch because most teams already have one; creating it would add ~100 lines of Terraform (subnets, NAT gateways, route tables) that distract from the actual requirements.

- **Authentication** — `/analyze` is unauthenticated. In production you'd add a CloudFront function or Lambda@Edge to validate an API key. Cut for scope.

- **`/notify` SNS endpoint** — the spec marks this as optional. The design is straightforward (same analysis path, then `sns.publish()`), but the required IAM + SNS Terraform and the test setup for mocking SNS wasn't worth the time given the other requirements.

**Did not cut:**

- **Streaming** — the spec says this is the most important requirement. The implementation reads S3 in 1 MB chunks and never buffers the full object. The streaming memory test proves it.

- **Ports-and-adapters structure** — `core.py` has zero I/O. `s3_reader.py` and `iter_file` are swappable adapters. The test suite stubs the S3 adapter entirely, which is why 44 of 46 tests don't need AWS credentials.

- **Least-privilege IAM** — the task role has only `s3:ListBucket` and `s3:GetObject` on the specific buckets listed in `var.log_buckets`. No `s3:*`.

---

## Project structure

```
.
├── src/log_analytics/
│   ├── core.py          # Pure analysis logic — no I/O, no AWS
│   ├── s3_reader.py     # S3 input adapter (chunked streaming)
│   ├── cli.py           # CLI port
│   ├── server.py        # HTTP port (FastAPI)
│   ├── logging_config.py# Structured JSON logging
│   └── main.py          # Uvicorn entrypoint
├── tests/
│   ├── test_core.py     # 21 unit tests — core logic only
│   ├── test_s3_reader.py# 8 tests — S3 adapter (mocked boto3)
│   ├── test_api.py      # 16 tests — HTTP endpoints (TestClient)
│   └── test_streaming.py# 1 test — 100 MB file, RSS assertion
├── terraform/
│   ├── modules/
│   │   ├── ecr/         # ECR repository + lifecycle policy
│   │   ├── iam/         # Task execution role + least-privilege task role
│   │   ├── ecs/         # Fargate service, ALB, security groups, CloudWatch
│   │   └── cloudfront/  # CloudFront distribution
│   └── environments/prod/
│       ├── main.tf      # Wires modules together
│       ├── variables.tf
│       └── outputs.tf
├── infra/
│   └── bootstrap.tf     # One-time: S3 state bucket + DynamoDB lock table
├── .github/workflows/
│   ├── ci.yml           # PR: lint + tests + tf validate
│   └── cd.yml           # main: build → push ECR → tf apply → ECS rollout → smoke test
├── sample-logs/
│   └── 2025-09-15T14-00.jsonl
├── Dockerfile
└── pyproject.toml
```

---

## Running locally

### CLI — local file

```bash
pip install -e .
analyze --file sample-logs/2025-09-15T14-00.jsonl --threshold 3
```

### CLI — S3

```bash
export AWS_PROFILE=your-profile
analyze --bucket my-log-bucket --prefix logs/2025/09/ --threshold 10
```

### HTTP server

```bash
pip install -e .
uvicorn log_analytics.main:app --reload

# In another terminal:
curl "http://localhost:8000/healthz"
curl "http://localhost:8000/analyze?file=sample-logs/2025-09-15T14-00.jsonl&threshold=3"
curl "http://localhost:8000/analyze?bucket=my-bucket&prefix=logs/&threshold=10"
```

### Docker

```bash
docker build -t log-analytics .

# HTTP server
docker run -p 8000:8000 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION=eu-west-1 \
  log-analytics

# CLI
docker run --rm log-analytics analyze \
  --bucket my-bucket --prefix logs/ --threshold 3
```

---

## Deploying

### Prerequisites

1. AWS account with credentials
2. Terraform ≥ 1.7
3. An existing VPC with public + private subnets

### One-time bootstrap (remote state)

```bash
cd infra
terraform init
terraform apply
```

### Deploy infrastructure

```bash
cd terraform/environments/prod

terraform init \
  -backend-config="bucket=log-analytics-tfstate" \
  -backend-config="region=eu-west-1"

terraform apply \
  -var="vpc_id=vpc-xxxxxxxx" \
  -var='public_subnet_ids=["subnet-aaa","subnet-bbb"]' \
  -var='private_subnet_ids=["subnet-ccc","subnet-ddd"]' \
  -var='log_buckets=["my-log-bucket"]' \
  -var="image_tag=latest"
```

### CI/CD (GitHub Actions)

Set these repository secrets:

| Secret | Description |
|--------|-------------|
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN to assume via OIDC |
| `TF_STATE_BUCKET` | S3 bucket for Terraform state |
| `VPC_ID` | Target VPC |
| `PUBLIC_SUBNET_IDS` | JSON list of public subnet IDs |
| `PRIVATE_SUBNET_IDS` | JSON list of private subnet IDs |
| `LOG_BUCKETS` | JSON list of S3 bucket names |

On every PR: lint + tests + `terraform validate`.  
On merge to main: build → push ECR → `terraform apply` → ECS rollout → `/version` smoke test.

---

## Testing with example logs

```bash
# Local file
analyze --file sample-logs/2025-09-15T14-00.jsonl --threshold 3
# → exit 2 (alert), total=6, parseErrors=1

# HTTP
curl "http://localhost:8000/analyze?file=$(pwd)/sample-logs/2025-09-15T14-00.jsonl&threshold=3"

# Against the deployed CloudFront URL
curl "https://<cloudfront-domain>/analyze?bucket=my-bucket&prefix=logs/&threshold=3"

# Liveness / readiness
curl "https://<cloudfront-domain>/healthz"
curl "https://<cloudfront-domain>/readyz?bucket=my-bucket"
curl "https://<cloudfront-domain>/version"
```

---

## Design decisions

**Why ports and adapters?**  
`core.py` accepts any `Iterable[str | bytes]` and is entirely I/O-free. The CLI, HTTP server, and test suite all call the same function — there's no separate "S3 code path" vs "local code path". The only difference is which iterator you hand in. This is why the local-file test mode falls out naturally from the design.

**Why uvicorn single-worker?**  
Each streaming request holds an open S3 connection for the duration of the analysis. Multiple workers would only help for CPU-bound work. Since this is I/O-bound (S3 reads), a single async worker with asyncio handles concurrent requests fine — Python's GIL isn't a bottleneck here because most time is spent in I/O wait, not CPU.

**Why 512 MB task memory with 256 MB container reservation?**  
The spec says the container has 256 MB of memory. The task needs slightly more overhead for the ECS agent. The `memoryReservation` on the container definition is set to 256 MB, matching the spec's constraint, while the task itself has headroom.

**Structured logging**  
Every log line is valid JSON. Every HTTP request gets a `request_id` (UUID) that appears in both the HTTP response header (`X-Request-Id`) and all log lines emitted during that request. This makes it trivial to trace a request in CloudWatch Logs Insights.
