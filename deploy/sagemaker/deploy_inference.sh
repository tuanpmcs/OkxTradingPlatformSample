#!/usr/bin/env bash
set -euo pipefail

# End-to-end helper:
# 1) builds inference image
# 2) pushes to ECR
# 3) creates/updates SageMaker endpoint
#
# Required env vars:
#   AWS_REGION
#   AWS_ACCOUNT_ID
#   SAGEMAKER_ROLE_ARN
#   S3_MODEL_URI (s3://.../model.tar.gz)
#
# Optional env vars:
#   ECR_REPOSITORY=okx-trading/inference-python
#   IMAGE_TAG=latest
#   ENDPOINT_NAME=okx-pulse-inference
#   INSTANCE_TYPE=ml.c7i.large
#   INITIAL_INSTANCE_COUNT=1
#   WAIT_FOR_ENDPOINT=true
#   MODEL_PATH_ENV=/opt/ml/model/pulse_xgboost_v1.joblib
#   MODEL_DIR_ENV=/opt/ml/model

: "${AWS_REGION:?Set AWS_REGION}"
: "${SAGEMAKER_ROLE_ARN:?Set SAGEMAKER_ROLE_ARN}"
: "${S3_MODEL_URI:?Set S3_MODEL_URI (s3://.../model.tar.gz)}"

ECR_REPOSITORY="${ECR_REPOSITORY:-okx-trading/inference-python}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
ENDPOINT_NAME="${ENDPOINT_NAME:-okx-pulse-inference}"
INSTANCE_TYPE="${INSTANCE_TYPE:-ml.c7i.large}"
INITIAL_INSTANCE_COUNT="${INITIAL_INSTANCE_COUNT:-1}"
WAIT_FOR_ENDPOINT="${WAIT_FOR_ENDPOINT:-true}"
MODEL_PATH_ENV="${MODEL_PATH_ENV:-/opt/ml/model/pulse_xgboost_v1.joblib}"
MODEL_DIR_ENV="${MODEL_DIR_ENV:-/opt/ml/model}"
ALLOW_CROSS_ACCOUNT="${ALLOW_CROSS_ACCOUNT:-false}"
PUSH_RETRIES="${PUSH_RETRIES:-5}"
PUSH_RETRY_SLEEP_SEC="${PUSH_RETRY_SLEEP_SEC:-6}"

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
  echo "Set ALLOW_CROSS_ACCOUNT=true only if cross-account ECR push is intended and policy is configured."
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_IMAGE="okx-trading/inference-python:${IMAGE_TAG}"
ECR_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "[1/5] Ensure ECR repository exists: ${ECR_REPOSITORY}"
"${AWS_CLI[@]}" ecr create-repository --region "${AWS_REGION}" --repository-name "${ECR_REPOSITORY}" >/dev/null 2>&1 || true

echo "[2/5] Login to ECR"
"${AWS_CLI[@]}" ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "[3/5] Build inference image"
docker build \
  -f "${REPO_ROOT}/deploy/containers/Dockerfile.inference-python" \
  --build-arg INSTALL_PROFILE=inference \
  -t "${LOCAL_IMAGE}" \
  "${REPO_ROOT}"

echo "[4/5] Push image to ECR: ${ECR_IMAGE_URI}"
docker tag "${LOCAL_IMAGE}" "${ECR_IMAGE_URI}"
push_ok=false
for attempt in $(seq 1 "${PUSH_RETRIES}"); do
  if docker push "${ECR_IMAGE_URI}"; then
    push_ok=true
    break
  fi
  echo "Push attempt ${attempt}/${PUSH_RETRIES} failed."
  if [[ "${attempt}" -lt "${PUSH_RETRIES}" ]]; then
    echo "Retrying in ${PUSH_RETRY_SLEEP_SEC}s..."
    sleep "${PUSH_RETRY_SLEEP_SEC}"
  fi
done

if [[ "${push_ok}" != "true" ]]; then
  echo "ERROR: docker push failed after ${PUSH_RETRIES} attempts."
  echo "If error includes 192.168.65.1:3128, this is usually a Docker proxy/VPN connection reset."
  echo "Try restarting Docker Desktop, checking proxy settings, or setting NO_PROXY for *.amazonaws.com."
  exit 1
fi

echo "[5/5] Create/update SageMaker endpoint: ${ENDPOINT_NAME}"
WAIT_ARG=""
if [[ "${WAIT_FOR_ENDPOINT}" == "true" ]]; then
  WAIT_ARG="--wait"
fi

python3 "${REPO_ROOT}/deploy/sagemaker/deploy_endpoint.py" \
  --region "${AWS_REGION}" \
  --role-arn "${SAGEMAKER_ROLE_ARN}" \
  --endpoint-name "${ENDPOINT_NAME}" \
  --image-uri "${ECR_IMAGE_URI}" \
  --model-data-url "${S3_MODEL_URI}" \
  --instance-type "${INSTANCE_TYPE}" \
  --initial-instance-count "${INITIAL_INSTANCE_COUNT}" \
  --model-path-env "${MODEL_PATH_ENV}" \
  --model-dir-env "${MODEL_DIR_ENV}" \
  ${WAIT_ARG}

echo "Done. Endpoint deployment submitted for ${ENDPOINT_NAME}."
