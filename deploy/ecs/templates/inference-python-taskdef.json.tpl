{
  "family": "okx-inference-python",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["EC2", "FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "${EXECUTION_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "containerDefinitions": [
    {
      "name": "inference-python",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/okx-trading/inference-python:${IMAGE_TAG}",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 50061,
          "protocol": "tcp"
        }
      ],
      "environment": [
        { "name": "SERVING_MODE", "value": "grpc" },
        { "name": "MODEL_PATH", "value": "/app/models/pulse_xgboost_v1.joblib" },
        { "name": "MODEL_DIR_PATH", "value": "/app/models" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "${LOG_GROUP_PREFIX}/okx-inference-python",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
