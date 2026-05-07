# Course Project Mapping

## Project title

`OKX Pulse: Real-Time HFT Signal Inference Platform`

## Why it fits the assignment

- Microservice-based application
- Container deployment
- Real-time inference
- AWS deployment comparison

## Requirement mapping

| Requirement | Repo location |
| --- | --- |
| Containerized services | `deploy/containers/` |
| ECR helpers | `deploy/ecs/create_ecr_repos.sh` |
| ECS task definitions | `deploy/ecs/templates/` |
| EC2 runtime path | `deploy/ec2/` |
| ECS EC2 and Fargate comparison | `docs/aws_ec2_vs_fargate_comparison.md` |
| Load balancing | `web-gateway` behind ALB |
| Monitoring and logs | CloudWatch and ECS metrics |

## Demo flow

1. Show the local service architecture.
2. Show the three container images.
3. Show ECS on EC2.
4. Show ECS on Fargate.
5. Show ALB health and `/predict`.
6. Show logs and metrics.
7. Show the EC2 vs Fargate comparison table.
