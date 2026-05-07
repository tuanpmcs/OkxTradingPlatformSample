# Deployment

OKX Pulse can run locally through Docker Compose and can be deployed to AWS through the ECS/EC2 assets in `deploy/`.

## Local container run

Runtime stack:

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime up --build
```

Training stack:

```bash
docker compose -f deploy/containers/docker-compose.yml --profile training up --build model-trainer
```

Main files:

- `deploy/containers/Dockerfile.backend-cpp`
- `deploy/containers/Dockerfile.inference-python`
- `deploy/containers/Dockerfile.web-gateway`
- `deploy/containers/docker-compose.yml`

## AWS deployment

- `deploy/ecs/`: ECS task definitions, services, and operational scripts
- `deploy/ec2/`: EC2 runtime path for the C++ stream service
- `deploy/terraform/`: infrastructure scope and suggested Terraform layout

Core services:

| Service | Container | Interface |
| --- | --- | --- |
| `backend-cpp` | `Dockerfile.backend-cpp` | `gRPC :50051` |
| `inference-python` | `Dockerfile.inference-python` | `gRPC :50061` |
| `web-gateway` | `Dockerfile.web-gateway` | `HTTP :8080` |

## Recommendation

- Use `ECS on EC2` for the lowest steady-state cost and most control
- Use `ECS on Fargate` when simpler operations matter more than cost
- Keep the inference hop on the internal gRPC path for the main runtime flow

## Submission notes

- Do not include local build directories, model artifacts, datasets, virtual environments, or `node_modules/`.
- Use `scripts/prepare_submission.sh` from the repository root to create a clean zip.
- See `aws_ec2_vs_fargate_comparison.md` for the cost and benchmark checklist.
