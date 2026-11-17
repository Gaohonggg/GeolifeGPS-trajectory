# ECS cluster (không tốn tiền khi không có task) và log group dùng chung.

resource "aws_ecs_cluster" "main" {
  name = local.name
  # Container Insights sinh nhiều custom metric tính tiền (Plan mục 4.4)
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}
