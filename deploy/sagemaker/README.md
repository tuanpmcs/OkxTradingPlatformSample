# SageMaker Deployment (Model Hosting)

This folder contains deployment helpers for pushing trained artifacts to SageMaker.

## Quick path (recommended)

Use the end-to-end helper to build/push image + deploy endpoint in one command:

```bash
export AWS_REGION=<region>
export AWS_ACCOUNT_ID=<account>
export SAGEMAKER_ROLE_ARN=arn:aws:iam::<account>:role/<SageMakerExecutionRole>
export S3_MODEL_URI=s3://<your-bucket>/models/pulse_xgboost_v1/model.tar.gz

bash deploy/sagemaker/deploy_inference.sh
```

Optional variables: `ENDPOINT_NAME`, `IMAGE_TAG`, `INSTANCE_TYPE`, `INITIAL_INSTANCE_COUNT`, `WAIT_FOR_ENDPOINT`.

## Important

This repository's default local serving path is gRPC (`ml_pipeline.serving.app`).
For SageMaker hosting, the inference container now starts a SageMaker-compatible HTTP server
(`ml_pipeline.serving.sagemaker_http`) by default and serves `/ping` + `/invocations` on port `8080`.

Set `SERVING_MODE=grpc` only if you want the legacy local gRPC mode in the same container.

## 1) Prepare model artifact

From repo root:

```bash
tar -czf model.tar.gz -C models pulse_xgboost_v1.joblib
```

Upload to S3:

```bash
aws s3 cp model.tar.gz s3://<your-bucket>/models/pulse_xgboost_v1/model.tar.gz
```

## 2) Build and push inference image to ECR

```bash
aws ecr create-repository --repository-name okx-trading/inference-python || true

aws ecr get-login-password --region <region> \
  | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com

docker build -f deploy/containers/Dockerfile.inference-python \
  --build-arg INSTALL_PROFILE=inference \
  -t okx-trading/inference-python:latest .

docker tag okx-trading/inference-python:latest \
  <account>.dkr.ecr.<region>.amazonaws.com/okx-trading/inference-python:latest

docker push <account>.dkr.ecr.<region>.amazonaws.com/okx-trading/inference-python:latest
```

## 3) Create or update endpoint

Use the helper script:

```bash
python deploy/sagemaker/deploy_endpoint.py \
  --region <region> \
  --role-arn arn:aws:iam::<account>:role/<SageMakerExecutionRole> \
  --endpoint-name okx-pulse-inference \
  --image-uri <account>.dkr.ecr.<region>.amazonaws.com/okx-trading/inference-python:latest \
  --model-data-url s3://<your-bucket>/models/pulse_xgboost_v1/model.tar.gz \
  --instance-type ml.c7i.large \
  --initial-instance-count 1 \
  --wait
```

## 4) Invoke endpoint

```bash
aws sagemaker-runtime invoke-endpoint \
  --region <region> \
  --endpoint-name okx-pulse-inference \
  --content-type application/json \
  --body '{"symbol":"BTC-USDT","channel":"books5","horizon_sec":30,"points":[{"ts":1,"price":100.0}]}' \
  /tmp/sm_response.json && cat /tmp/sm_response.json
```

## Notes

- Keep HFT decision loops local; SageMaker should be used for scalable managed hosting, not sub-ms critical paths.
- For strict production usage, pin dependency versions and add IAM-scoped roles for model + endpoint operations.
- SageMaker endpoint contract is HTTP; the container default now matches this requirement.
- C++ stream runtime currently does not call SageMaker HTTP directly; deploy it separately on EC2 (`deploy/ec2`).
