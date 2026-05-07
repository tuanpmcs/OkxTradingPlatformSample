#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION}"

AWS_CLI=(aws)
if [[ -n "${AWS_PROFILE:-}" ]]; then
  AWS_CLI+=(--profile "${AWS_PROFILE}")
fi

CALLER_ACCOUNT="$("${AWS_CLI[@]}" sts get-caller-identity --query Account --output text)"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-${CALLER_ACCOUNT}}"

REPOSITORIES=(
  "okx-trading/backend-cpp"
  "okx-trading/inference-python"
  "okx-trading/web-gateway"
)

for repo in "${REPOSITORIES[@]}"; do
  echo "Ensuring ECR repository exists: ${repo}"
  "${AWS_CLI[@]}" ecr create-repository \
    --region "${AWS_REGION}" \
    --repository-name "${repo}" >/dev/null 2>&1 || true
done

echo "Done. Repositories ready in account ${AWS_ACCOUNT_ID}, region ${AWS_REGION}."
