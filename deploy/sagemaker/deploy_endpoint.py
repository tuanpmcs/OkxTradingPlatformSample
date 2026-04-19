#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError


@dataclass
class DeployConfig:
    region: str
    role_arn: str
    endpoint_name: str
    image_uri: str
    model_data_url: str
    instance_type: str
    initial_instance_count: int
    model_name: str
    endpoint_config_name: str
    model_path_env: str
    model_dir_env: str
    wait: bool


def parse_args() -> DeployConfig:
    p = argparse.ArgumentParser(description="Create or update SageMaker endpoint for model serving.")
    p.add_argument("--region", required=True, help="AWS region, e.g. us-east-1")
    p.add_argument("--role-arn", required=True, help="SageMaker execution role ARN")
    p.add_argument("--endpoint-name", required=True, help="Endpoint name")
    p.add_argument("--image-uri", required=True, help="ECR image URI")
    p.add_argument("--model-data-url", required=True, help="S3 model artifact tar.gz, s3://...")
    p.add_argument("--instance-type", default="ml.c7i.large", help="Endpoint instance type")
    p.add_argument("--initial-instance-count", type=int, default=1, help="Initial instance count")
    p.add_argument(
        "--model-path-env",
        default="/opt/ml/model/pulse_xgboost_v1.joblib",
        help="MODEL_PATH env passed to container",
    )
    p.add_argument(
        "--model-dir-env",
        default="/opt/ml/model",
        help="MODEL_DIR_PATH env passed to container",
    )
    p.add_argument("--wait", action="store_true", help="Wait until endpoint is InService")
    args = p.parse_args()

    stamp = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    endpoint_slug = args.endpoint_name.replace("_", "-")
    return DeployConfig(
        region=args.region,
        role_arn=args.role_arn,
        endpoint_name=args.endpoint_name,
        image_uri=args.image_uri,
        model_data_url=args.model_data_url,
        instance_type=args.instance_type,
        initial_instance_count=max(1, args.initial_instance_count),
        model_name=f"{endpoint_slug}-model-{stamp}",
        endpoint_config_name=f"{endpoint_slug}-cfg-{stamp}",
        model_path_env=args.model_path_env,
        model_dir_env=args.model_dir_env,
        wait=args.wait,
    )


def endpoint_exists(sm_client, endpoint_name: str) -> bool:
    try:
        sm_client.describe_endpoint(EndpointName=endpoint_name)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"ValidationException", "ResourceNotFound"}:
            return False
        raise


def main() -> None:
    cfg = parse_args()
    sm = boto3.client("sagemaker", region_name=cfg.region)

    print(f"[1/4] create_model: {cfg.model_name}")
    sm.create_model(
        ModelName=cfg.model_name,
        ExecutionRoleArn=cfg.role_arn,
        PrimaryContainer={
            "Image": cfg.image_uri,
            "ModelDataUrl": cfg.model_data_url,
            "Environment": {
                "MODEL_PATH": cfg.model_path_env,
                "MODEL_DIR_PATH": cfg.model_dir_env,
            },
        },
    )

    print(f"[2/4] create_endpoint_config: {cfg.endpoint_config_name}")
    sm.create_endpoint_config(
        EndpointConfigName=cfg.endpoint_config_name,
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": cfg.model_name,
                "InitialInstanceCount": cfg.initial_instance_count,
                "InstanceType": cfg.instance_type,
                "InitialVariantWeight": 1.0,
            }
        ],
    )

    if endpoint_exists(sm, cfg.endpoint_name):
        print(f"[3/4] update_endpoint: {cfg.endpoint_name}")
        sm.update_endpoint(
            EndpointName=cfg.endpoint_name,
            EndpointConfigName=cfg.endpoint_config_name,
        )
    else:
        print(f"[3/4] create_endpoint: {cfg.endpoint_name}")
        sm.create_endpoint(
            EndpointName=cfg.endpoint_name,
            EndpointConfigName=cfg.endpoint_config_name,
        )

    if cfg.wait:
        print("[4/4] waiting for endpoint to become InService ...")
        waiter = sm.get_waiter("endpoint_in_service")
        waiter.wait(EndpointName=cfg.endpoint_name)
        print("Endpoint is InService.")
    else:
        print("[4/4] submitted (use --wait to block until InService).")


if __name__ == "__main__":
    main()
