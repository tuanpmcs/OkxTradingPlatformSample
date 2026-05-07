# Terraform Scope for the AWS HFT Deployment

Use Terraform here to provision the cloud foundation for the assignment:

- VPC
- public/private subnets
- NAT gateway
- ECS cluster
- ECS capacity provider for EC2
- Application Load Balancer
- target groups
- security groups
- CloudWatch log groups
- IAM roles for ECS task execution

## Suggested Modules

```text
deploy/terraform/
  main.tf
  variables.tf
  outputs.tf
  vpc.tf
  ecs.tf
  alb.tf
  iam.tf
  cloudwatch.tf
```

## Recommended State Boundary

Keep this project in one platform stack, or split it into `network` and `services` stacks if you want cleaner demos:

1. `network`
   - VPC
   - subnets
   - security groups
2. `services`
   - ECS
   - ALB
   - IAM
   - CloudWatch

## What to Demonstrate

For the course submission, Terraform does not need to automate every single runtime action.
It is enough if it reproducibly creates:

- networking
- cluster resources
- load balancer
- logging resources
- IAM roles

Then deploy task definitions and services using the ECS templates in `deploy/ecs`.
