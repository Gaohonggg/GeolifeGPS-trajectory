# ECS cluster và log group dùng chung cho mọi task. Cluster không tính phí khi không có task.

resource "aws_ecs_cluster" "main" {
  name = local.name
  # Container Insights sinh nhiều custom metric, mỗi metric tính phí.
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}
