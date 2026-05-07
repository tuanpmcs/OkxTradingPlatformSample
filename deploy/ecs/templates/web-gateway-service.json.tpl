{
  "serviceName": "okx-web-gateway",
  "cluster": "${ECS_CLUSTER_NAME}",
  "taskDefinition": "okx-web-gateway",
  "desiredCount": 2,
  "launchType": "${LAUNCH_TYPE}",
  "enableExecuteCommand": true,
  "loadBalancers": [
    {
      "targetGroupArn": "${TARGET_GROUP_ARN}",
      "containerName": "web-gateway",
      "containerPort": 8080
    }
  ],
  "networkConfiguration": {
    "awsvpcConfiguration": {
      "subnets": ${PRIVATE_SUBNET_IDS},
      "securityGroups": ["${SERVICE_SECURITY_GROUP_ID}"],
      "assignPublicIp": "DISABLED"
    }
  }
}
