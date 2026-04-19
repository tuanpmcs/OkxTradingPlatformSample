# EC2 Deployment (C++ Stream Runtime)

This folder provides scripts to run the C++ market stream runtime (`hello_world`) on EC2.

## Important integration note

The C++ runtime currently supports model inference via **gRPC** (`--inference-mode grpc`) or local fallback logic.
SageMaker endpoints are HTTP (`/invocations`).

That means the current deployment split is:

- SageMaker: managed Python model inference endpoint
- EC2: C++ stream runtime (typically with `--inference-mode off`)

If you later want C++ stream -> SageMaker direct inference, we need to add a SageMaker HTTP prediction client in `backend/src/inference`.

## 1) Build and push C++ image to ECR

From your local machine (repo root):

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012

bash deploy/ec2/push_backend_image.sh
```

Optional image settings:

```bash
export ECR_REPOSITORY=okx-trading/backend-cpp
export IMAGE_TAG=latest
```

## 2) Prepare EC2 instance

Recommended:

- Amazon Linux 2023 or Ubuntu 22.04+
- IAM instance profile with `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`
- Security Group inbound:
  - TCP `22` from your admin IP
  - TCP `50051` only from trusted clients (not `0.0.0.0/0`)

Install dependencies on EC2:

```bash
sudo dnf -y install docker awscli || sudo apt-get update && sudo apt-get install -y docker.io awscli
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
```

## 3) Run C++ stream container on EC2

Copy this repo (or at least `deploy/ec2/run_cpp_stream.sh`) to EC2, then:

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012
export INFERENCE_MODE=off

bash deploy/ec2/run_cpp_stream.sh
```

Useful optional vars:

```bash
export HOST_GRPC_PORT=50051
export TRACE_STREAM=true
export CONFIG_FILE=/opt/okx/okx_public.yaml
```

For local gRPC inference on the same EC2 host, set:

```bash
export INFERENCE_MODE=grpc
export INFERENCE_GRPC_TARGET=127.0.0.1:50061
```

## 4) Verify stream service

From EC2:

```bash
docker logs --tail 100 backend-cpp
```

From a trusted client network:

```bash
grpcurl -plaintext <ec2-private-or-public-ip>:50051 list
```

## 5) Update image version

```bash
export IMAGE_TAG=v2026-04-19
bash deploy/ec2/push_backend_image.sh
bash deploy/ec2/run_cpp_stream.sh
```
