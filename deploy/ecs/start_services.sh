#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
CLUSTER_NAME="${ECS_CLUSTER_NAME:-hft-cluster-arm}"
ASG_NAME="${ECS_EC2_ASG_NAME:-hft-cluster-arm-asg}"
EC2_BACKEND_SD_SERVICE_ID="${ECS_EC2_BACKEND_SD_SERVICE_ID:-srv-tz7aidtjldymi25l}"
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

select_backend_host() {
  python - <<'PY'
import json
import os
import subprocess
import sys

region = os.environ["REGION"]
cluster = os.environ["CLUSTER_NAME"]

list_cmd = [
    "aws", "ecs", "list-container-instances",
    "--region", region,
    "--cluster", cluster,
    "--query", "containerInstanceArns",
    "--output", "json",
]
arns = json.loads(subprocess.check_output(list_cmd, text=True))
if not arns:
    sys.exit(1)

describe_cmd = [
    "aws", "ecs", "describe-container-instances",
    "--region", region,
    "--cluster", cluster,
    "--container-instances",
    *arns,
    "--output", "json",
]
data = json.loads(subprocess.check_output(describe_cmd, text=True))

eligible = []
for item in data.get("containerInstances", []):
    if item.get("status") != "ACTIVE" or not item.get("agentConnected"):
        continue
    remaining = {r["name"]: r.get("integerValue", 0) for r in item.get("remainingResources", [])}
    if remaining.get("MEMORY", 0) >= 1024 and remaining.get("CPU", 0) >= 512:
        eligible.append((remaining.get("MEMORY", 0), remaining.get("CPU", 0), item.get("ec2InstanceId", "")))

if not eligible:
    sys.exit(1)

eligible.sort(reverse=True)
print(eligible[0][2])
PY
}

pin_backend_service() {
  local instance_id
  for _ in $(seq 1 24); do
    if instance_id="$(select_backend_host 2>/dev/null)"; then
      BACKEND_INSTANCE_ID="${instance_id}"
      echo "Pinning okx-backend-cpp to active EC2 container instance ${instance_id}"
      aws ecs update-service \
        --region "${REGION}" \
        --cluster "${CLUSTER_NAME}" \
        --service okx-backend-cpp \
        --placement-constraints "type=memberOf,expression=ec2InstanceId == ${instance_id}" \
        >/dev/null
      return 0
    fi
    echo "Waiting for an eligible ECS container instance for okx-backend-cpp..."
    sleep 5
  done

  echo "No eligible ECS container instance found for okx-backend-cpp" >&2
  exit 1
}

sync_backend_service_discovery() {
  local instance_id="${BACKEND_INSTANCE_ID:-}"
  local private_ip=""
  local existing_ids=""

  if [ -z "${instance_id}" ]; then
    echo "No backend instance selected for service discovery sync" >&2
    exit 1
  fi

  private_ip="$(aws ec2 describe-instances \
    --region "${REGION}" \
    --instance-ids "${instance_id}" \
    --query 'Reservations[0].Instances[0].PrivateIpAddress' \
    --output text)"

  if [ -z "${private_ip}" ] || [ "${private_ip}" = "None" ]; then
    echo "Unable to resolve private IP for ${instance_id}" >&2
    exit 1
  fi

  echo "Registering stable Cloud Map DNS backend-cpp-ec2.hft.local -> ${private_ip}"
  existing_ids="$(aws servicediscovery list-instances \
    --region "${REGION}" \
    --service-id "${EC2_BACKEND_SD_SERVICE_ID}" \
    --query 'Instances[].Id' \
    --output text 2>/dev/null || true)"

  for existing_id in ${existing_ids}; do
    if [ "${existing_id}" != "${instance_id}" ]; then
      aws servicediscovery deregister-instance \
        --region "${REGION}" \
        --service-id "${EC2_BACKEND_SD_SERVICE_ID}" \
        --instance-id "${existing_id}" \
        >/dev/null || true
    fi
  done

  aws servicediscovery register-instance \
    --region "${REGION}" \
    --service-id "${EC2_BACKEND_SD_SERVICE_ID}" \
    --instance-id "${instance_id}" \
    --attributes "AWS_INSTANCE_IPV4=${private_ip}" \
    >/dev/null
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

start_ec2() {
  echo "Scaling Auto Scaling Group ${ASG_NAME} to min=3 max=3 desired=3"
  aws autoscaling update-auto-scaling-group \
    --region "${REGION}" \
    --auto-scaling-group-name "${ASG_NAME}" \
    --min-size 3 \
    --max-size 3 \
    --desired-capacity 3

  pin_backend_service
  sync_backend_service_discovery
  scale_services 1 "${EC2_SERVICES[@]}"
  wait_stable "${EC2_SERVICES[@]}"
}

start_fargate() {
  scale_services 1 "${FARGATE_SERVICES[@]}"
  wait_stable "${FARGATE_SERVICES[@]}"
}

case "${MODE}" in
  ec2)
    start_ec2
    ;;
  fargate)
    start_fargate
    ;;
  all)
    start_ec2
    start_fargate
    ;;
  *)
    usage
    ;;
esac

echo "Done."
