# ECS Deployment Pack for the OKX Pulse HFT Platform

This folder turns the current repository into a course-ready microservice deployment project.

## Chosen Service Application

Use this project as:

`OKX Pulse HFT Signal Platform`

It is a microservice-based trading intelligence system with three deployable services:

1. `backend-cpp`
   - consumes OKX market data
   - reconstructs order book state
   - builds rolling live features
   - exposes gRPC market stream output
2. `inference-python`
   - loads trained ML models
   - serves real-time prediction over gRPC
3. `web-gateway`
   - exposes REST `/health`, `/market/latest`, `/predict`
   - sits behind an ALB for browser/API clients

This makes the application distinct from generic shopping or ticket systems while still satisfying the microservice requirement.

## What This Folder Contains

- `create_ecr_repos.sh`: create required ECR repositories
- `push_images.sh`: build and push all three service images
- `templates/*.json.tpl`: ECS task definition and service templates

## AWS Architecture

Recommended assignment architecture:

```text
Internet
  -> Application Load Balancer
      -> web-gateway ECS service
          -> inference-python ECS service (gRPC :50061)
          -> backend-cpp ECS service (gRPC :50051)
              -> OKX public websocket
```

This gives you:

- ECS on EC2
- ECS on Fargate
- ALB-based load balancing
- CloudWatch logs/metrics

## ECR Repositories

Create these repositories:

- `okx-trading/backend-cpp`
- `okx-trading/inference-python`
- `okx-trading/web-gateway`

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012
bash deploy/ecs/create_ecr_repos.sh
```

## Push Images

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=123456789012
bash deploy/ecs/push_images.sh
```

## ECS Task Definitions

Templates live under `deploy/ecs/templates`.

Render them with `envsubst` or a simple replacement step after exporting:

- `AWS_ACCOUNT_ID`
- `AWS_REGION`
- `IMAGE_TAG`
- `EXECUTION_ROLE_ARN`
- `TASK_ROLE_ARN`
- `LOG_GROUP_PREFIX`
- `PRIVATE_SUBNET_IDS`
- `SERVICE_SECURITY_GROUP_ID`
- `TARGET_GROUP_ARN`
- `ECS_CLUSTER_NAME`
- `INFERENCE_GRPC_TARGET`
- `PRED_GRPC_TARGET`
- `MARKET_GRPC_TARGET`

Suggested families:

- `okx-backend-cpp`
- `okx-inference-python`
- `okx-web-gateway`

## EC2 Deployment Path

Use an ECS cluster backed by EC2 Auto Scaling capacity.

Recommended fair comparison sizing:

- 2 x `t3.large` ECS container instances for EC2 mode
- same desired task counts and same container CPU/memory reservations as Fargate mode
- same ALB, same health checks, same CloudWatch log retention

Suggested desired counts:

- `backend-cpp`: 1
- `inference-python`: 2
- `web-gateway`: 2

Why this is fair:

- `backend-cpp` is mostly a singleton market-ingest worker
- `inference-python` and `web-gateway` are the horizontally scalable parts
- ALB distributes traffic evenly to the same edge service shape

## Fargate Deployment Path

Use a second ECS cluster or second service set in the same cluster with launch type `FARGATE`.

Mirror the same service counts:

- `backend-cpp`: 1
- `inference-python`: 2
- `web-gateway`: 2

Recommended Fargate sizing:

- `backend-cpp`: `1024 CPU / 2048 MiB`
- `inference-python`: `1024 CPU / 2048 MiB`
- `web-gateway`: `512 CPU / 1024 MiB`

## Load Balancing

Attach `web-gateway` to an ALB target group.

Recommended listeners:

- `:80` -> redirect to `:443`
- `:443` -> `web-gateway`

Suggested health check:

- path: `/health`
- matcher: `200`

If you want to compare EC2 vs Fargate live, create two target groups and two listener rules:

- `/ec2/*` -> EC2-backed `web-gateway`
- `/fargate/*` -> Fargate-backed `web-gateway`

That gives you a nice apples-to-apples demonstration path.

## Monitoring and Logging

Use:

- CloudWatch Logs per service:
  - `/ecs/okx-backend-cpp`
  - `/ecs/okx-inference-python`
  - `/ecs/okx-web-gateway`
- Container Insights on the ECS cluster
- ALB metrics:
  - request count
  - target response time
  - HTTP 5xx
- ECS metrics:
  - CPU utilization
  - memory utilization
  - task restarts

Recommended custom metrics for comparison:

- median `/predict` latency
- p95 `/predict` latency
- requests per minute sustained before errors rise
- daily estimated cost at the same traffic level

## Fair EC2 vs Fargate Comparison

Keep these constants fixed:

- same Docker images
- same number of tasks
- same environment variables
- same ALB
- same request generator
- same test duration
- same payload size
- same autoscaling disabled during benchmark

Measure:

1. cold start / deployment speed
2. steady-state `/predict` latency
3. CPU and memory headroom
4. operational simplicity
5. estimated hourly and 24h cost

Use the comparison write-up in:

- [docs/aws_ec2_vs_fargate_comparison.md](/Volumes/Dev/Workspace/okx_trading_platform_sample/docs/aws_ec2_vs_fargate_comparison.md)
