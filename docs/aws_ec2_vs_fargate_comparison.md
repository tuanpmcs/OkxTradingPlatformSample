# EC2 vs Fargate Comparison

Use this file as the deployment benchmark and cost appendix.

## Compare the same app two ways

- `ECS on EC2`
- `ECS on Fargate`

Services under test:

- `backend-cpp`
- `inference-python`
- `web-gateway`

## Keep these the same

- Docker image tags
- task counts
- request payloads
- ALB health checks
- AWS region
- benchmark duration

## Measure

- p50, p95, and p99 `/predict` latency
- request throughput
- deployment time
- scale-out time
- hourly and monthly cost
- operational effort

## Result table

| Metric | ECS on EC2 | ECS on Fargate | Notes |
| --- | ---: | ---: | --- |
| p50 `/predict` latency | TBD | TBD | same request payload |
| p95 `/predict` latency | TBD | TBD | same benchmark duration |
| requests/sec | TBD | TBD | same task count |
| deploy time | TBD | TBD | image push excluded |
| scale-out time | TBD | TBD | service-level scaling |
| monthly cost | `~$36.79` | `~$90.10` | project estimate for always-on runtime |
| operational effort | higher | lower | EC2 requires host management |

## Expected conclusion

- EC2 is usually better for always-on cost and host control
- Fargate is usually better for operational simplicity
