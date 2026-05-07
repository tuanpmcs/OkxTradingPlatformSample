#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION}"

AWS_CLI=(aws)
if [[ -n "${AWS_PROFILE:-}" ]]; then
  AWS_CLI+=(--profile "${AWS_PROFILE}")
fi

CALLER_ACCOUNT="$("${AWS_CLI[@]}" sts get-caller-identity --query Account --output text)"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-${CALLER_ACCOUNT}}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

bash "${REPO_ROOT}/deploy/ecs/create_ecr_repos.sh"

echo "Logging into ECR ${ECR_REGISTRY}"
"${AWS_CLI[@]}" ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

build_and_push() {
  local dockerfile="$1"
  local local_image="$2"
  local remote_repo="$3"

  local local_tag="${local_image}:${IMAGE_TAG}"
  local remote_tag="${ECR_REGISTRY}/${remote_repo}:${IMAGE_TAG}"

  echo "Building ${local_tag}"
  docker build -f "${REPO_ROOT}/${dockerfile}" -t "${local_tag}" "${REPO_ROOT}"

  echo "Pushing ${remote_tag}"
  docker tag "${local_tag}" "${remote_tag}"
  docker push "${remote_tag}"
}

build_and_push "deploy/containers/Dockerfile.backend-cpp" "okx-trading/backend-cpp" "okx-trading/backend-cpp"
build_and_push "deploy/containers/Dockerfile.inference-python" "okx-trading/inference-python" "okx-trading/inference-python"
build_and_push "deploy/containers/Dockerfile.web-gateway" "okx-trading/web-gateway" "okx-trading/web-gateway"

echo "All service images pushed with tag ${IMAGE_TAG}"
