#!/usr/bin/env bash
set -euo pipefail

# Pulls backend-cpp image from ECR and runs the stream container on EC2.
# Required env vars:
#   AWS_REGION
#   AWS_ACCOUNT_ID
# Optional env vars:
#   ECR_REPOSITORY=okx-trading/backend-cpp
#   IMAGE_TAG=latest
#   CONTAINER_NAME=backend-cpp
#   HOST_GRPC_PORT=50051
#   GRPC_PORT=50051
#   INFERENCE_MODE=off      # off|grpc|onnx
#   INFERENCE_GRPC_TARGET=127.0.0.1:50061
#   INFERENCE_MODEL_TYPE=xgboost
#   INFERENCE_HORIZON_SEC=1
#   INFERENCE_TIMEOUT_MS=1200
#   INFERENCE_INTERVAL_MS=200
#   INFERENCE_MIN_POINTS=32
#   TRACE_STREAM=false
#   CONFIG_FILE=/opt/okx/okx_public.yaml

: "${AWS_REGION:?Set AWS_REGION}"

ECR_REPOSITORY="${ECR_REPOSITORY:-okx-trading/backend-cpp}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-backend-cpp}"
HOST_GRPC_PORT="${HOST_GRPC_PORT:-50051}"
GRPC_PORT="${GRPC_PORT:-50051}"
INFERENCE_MODE="${INFERENCE_MODE:-off}"
INFERENCE_GRPC_TARGET="${INFERENCE_GRPC_TARGET:-127.0.0.1:50061}"
INFERENCE_MODEL_TYPE="${INFERENCE_MODEL_TYPE:-xgboost}"
INFERENCE_HORIZON_SEC="${INFERENCE_HORIZON_SEC:-1}"
INFERENCE_TIMEOUT_MS="${INFERENCE_TIMEOUT_MS:-1200}"
INFERENCE_INTERVAL_MS="${INFERENCE_INTERVAL_MS:-200}"
INFERENCE_MIN_POINTS="${INFERENCE_MIN_POINTS:-32}"
TRACE_STREAM="${TRACE_STREAM:-false}"
CONFIG_FILE="${CONFIG_FILE:-}"
ALLOW_CROSS_ACCOUNT="${ALLOW_CROSS_ACCOUNT:-false}"

AWS_CLI=(aws)
if [[ -n "${AWS_PROFILE:-}" ]]; then
  AWS_CLI+=(--profile "${AWS_PROFILE}")
fi

CALLER_ACCOUNT="$("${AWS_CLI[@]}" sts get-caller-identity --query Account --output text)"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-${CALLER_ACCOUNT}}"
if [[ "${AWS_ACCOUNT_ID}" == "123456789012" ]]; then
  echo "ERROR: AWS_ACCOUNT_ID is the placeholder value 123456789012. Set your real account ID."
  exit 1
fi
if [[ "${AWS_ACCOUNT_ID}" != "${CALLER_ACCOUNT}" && "${ALLOW_CROSS_ACCOUNT}" != "true" ]]; then
  echo "ERROR: AWS_ACCOUNT_ID (${AWS_ACCOUNT_ID}) does not match caller account (${CALLER_ACCOUNT})."
  echo "Set ALLOW_CROSS_ACCOUNT=true only if cross-account ECR pull is intended and policy is configured."
  exit 1
fi

ECR_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "[1/4] Login to ECR"
"${AWS_CLI[@]}" ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "[2/4] Pull image ${ECR_IMAGE_URI}"
docker pull "${ECR_IMAGE_URI}"

echo "[3/4] Replace container ${CONTAINER_NAME} if it exists"
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

RUN_ARGS=(
  --detach
  --restart unless-stopped
  --name "${CONTAINER_NAME}"
  -p "${HOST_GRPC_PORT}:${GRPC_PORT}"
)

APP_ARGS=(
  --grpc-port "${GRPC_PORT}"
  --inference-mode "${INFERENCE_MODE}"
  --inference-model-type "${INFERENCE_MODEL_TYPE}"
  --inference-horizon-sec "${INFERENCE_HORIZON_SEC}"
  --inference-timeout-ms "${INFERENCE_TIMEOUT_MS}"
  --inference-interval-ms "${INFERENCE_INTERVAL_MS}"
  --inference-min-points "${INFERENCE_MIN_POINTS}"
)

if [[ -n "${CONFIG_FILE}" && -f "${CONFIG_FILE}" ]]; then
  RUN_ARGS+=( -v "${CONFIG_FILE}:/opt/app/configs/okx_public.yaml:ro" )
  APP_ARGS+=( --config /opt/app/configs/okx_public.yaml )
fi

if [[ "${INFERENCE_MODE}" == "grpc" ]]; then
  APP_ARGS+=( --inference-grpc-target "${INFERENCE_GRPC_TARGET}" )
fi

if [[ "${TRACE_STREAM}" == "true" ]]; then
  APP_ARGS+=( --trace-stream )
fi

echo "[4/4] Start container"
docker run "${RUN_ARGS[@]}" "${ECR_IMAGE_URI}" "${APP_ARGS[@]}"

echo "Container started: ${CONTAINER_NAME}"
docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
