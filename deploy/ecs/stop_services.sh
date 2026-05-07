#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
CLUSTER_NAME="${ECS_CLUSTER_NAME:-hft-cluster-arm}"
ASG_NAME="${ECS_EC2_ASG_NAME:-hft-cluster-arm-asg}"
MODE="${1:-all}"

EC2_SERVICES=(
  "okx-backend-cpp"
  "okx-inference-python"
  "okx-web-gateway"
)

FARGATE_SERVICES=(
  "okx-backend-cpp-fg"
  "okx-inference-python-fg"
  "okx-web-gateway-fg"
)

usage() {
  echo "Usage: $0 [ec2|fargate|all]"
  exit 1
}

scale_services() {
  local desired="$1"
  shift
  for service in "$@"; do
    echo "Updating ECS service ${service} -> desired=${desired}"
    aws ecs update-service \
      --region "${REGION}" \
      --cluster "${CLUSTER_NAME}" \
      --service "${service}" \
      --desired-count "${desired}" \
      >/dev/null
  done
}

wait_stable() {
  if [ "$#" -eq 0 ]; then
    return 0
  fi
  echo "Waiting for ECS services to reach steady state..."
  aws ecs wait services-stable \
    --region "${REGION}" \
    --cluster "${CLUSTER_NAME}" \
    --services "$@"
}

stop_ec2() {
  scale_services 0 "${EC2_SERVICES[@]}"
  wait_stable "${EC2_SERVICES[@]}"

  echo "Scaling Auto Scaling Group ${ASG_NAME} to min=0 max=0 desired=0"
  aws autoscaling update-auto-scaling-group \
    --region "${REGION}" \
    --auto-scaling-group-name "${ASG_NAME}" \
    --min-size 0 \
    --max-size 0 \
    --desired-capacity 0
}

stop_fargate() {
  scale_services 0 "${FARGATE_SERVICES[@]}"
  wait_stable "${FARGATE_SERVICES[@]}"
}

case "${MODE}" in
  ec2)
    stop_ec2
    ;;
  fargate)
    stop_fargate
    ;;
  all)
    stop_fargate
    stop_ec2
    ;;
  *)
    usage
    ;;
esac

echo "Done."
