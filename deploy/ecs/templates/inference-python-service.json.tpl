{
  "serviceName": "okx-inference-python",
  "cluster": "${ECS_CLUSTER_NAME}",
  "taskDefinition": "okx-inference-python",
  "desiredCount": 2,
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
