{
  "serviceName": "okx-backend-cpp",
  "cluster": "${ECS_CLUSTER_NAME}",
  "taskDefinition": "okx-backend-cpp",
  "desiredCount": 1,
  "launchType": "${LAUNCH_TYPE}",
  "enableExecuteCommand": true,
  "networkConfiguration": {
    "awsvpcConfiguration": {
      "subnets": ${PRIVATE_SUBNET_IDS},
      "securityGroups": ["${SERVICE_SECURITY_GROUP_ID}"],
      "assignPublicIp": "DISABLED"
    }
  }
}
