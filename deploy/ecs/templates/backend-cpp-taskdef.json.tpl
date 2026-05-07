{
  "family": "okx-backend-cpp",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["EC2", "FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "${EXECUTION_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "containerDefinitions": [
    {
      "name": "backend-cpp",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/okx-trading/backend-cpp:${IMAGE_TAG}",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 50051,
          "protocol": "tcp"
        }
      ],
      "command": [
        "--grpc-port", "50051",
        "--config", "/opt/app/configs/okx_public.yaml",
        "--inference-mode", "grpc",
        "--inference-grpc-target", "${INFERENCE_GRPC_TARGET}"
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "${LOG_GROUP_PREFIX}/okx-backend-cpp",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
