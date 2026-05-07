{
  "family": "okx-web-gateway",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["EC2", "FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "${EXECUTION_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "containerDefinitions": [
    {
      "name": "web-gateway",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/okx-trading/web-gateway:${IMAGE_TAG}",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8080,
          "protocol": "tcp"
        }
      ],
      "environment": [
        { "name": "PORT", "value": "8080" },
        { "name": "PRED_GRPC_TARGET", "value": "${PRED_GRPC_TARGET}" },
        { "name": "MARKET_GRPC_TARGET", "value": "${MARKET_GRPC_TARGET}" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "${LOG_GROUP_PREFIX}/okx-web-gateway",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
