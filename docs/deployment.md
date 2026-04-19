# Deployment

## Containers

- `deploy/containers/Dockerfile.backend-cpp`
- `deploy/containers/Dockerfile.inference-python`
- `deploy/containers/Dockerfile.web-gateway`
- `deploy/containers/Dockerfile.web-frontend`
- `deploy/containers/docker-compose.yml`

## Runtime compose

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime up --build
```

## Runtime + UI compose

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime --profile ui up --build
```

## Training compose

```bash
docker compose -f deploy/containers/docker-compose.yml --profile training up --build model-trainer
```

## Cloud extensions

Use `deploy/ecs`, `deploy/sagemaker`, and `deploy/terraform` for managed deployment expansion.

## AWS split deployment

- SageMaker inference endpoint: see `deploy/sagemaker/README.md` and `deploy/sagemaker/deploy_inference.sh`.
- EC2 C++ stream runtime: see `deploy/ec2/README.md`, `deploy/ec2/push_backend_image.sh`, and `deploy/ec2/run_cpp_stream.sh`.
