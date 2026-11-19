# Mỗi slot có version: một task definition (khác nhau ở MODEL_URI) và một ECS service gắn vào target group của slot.

data "aws_ecr_image" "api" {
  repository_name = split("/", local.foundation.ecr_repository_url)[1]
  image_tag       = var.image_tag
  most_recent     = var.image_tag == null ? true : null
}

locals {
  # Ghim theo digest: task definition luôn trỏ đúng một image.
  image = "${local.foundation.ecr_repository_url}@${data.aws_ecr_image.api.image_digest}"
}

resource "aws_ecs_task_definition" "api" {
  for_each                 = local.active_slots
  family                   = "${local.name}-api-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = local.foundation.execution_role_arn
  task_role_arn            = local.foundation.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = local.image
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      # Bản phát hành bất biến trên S3 (geolife.publish); task không gọi registry.
      { name = "MODEL_URI", value = "s3://${local.foundation.artifacts_bucket}/models/${var.model_name}/v=${each.value}/model" },
      { name = "DB_HOST", value = local.db.db_host },
      { name = "DB_PORT", value = tostring(local.db.db_port) },
      { name = "DB_NAME", value = local.db.db_name },
      { name = "DB_USER", value = local.db.db_user },
      { name = "AWS_REGION", value = var.region },
    ]
    secrets = [
      # Secret do RDS quản lý là JSON {"username", "password"}; ECS lấy riêng khoá password.
      { name = "DB_PASSWORD", valueFrom = "${local.db.db_secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = local.foundation.log_group_name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api-${each.key}"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  for_each        = local.active_slots
  name            = "api-${each.key}"
  cluster         = local.foundation.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.api[each.key].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.foundation.public_subnet_ids
    security_groups  = [local.foundation.task_security_group_id]
    assign_public_ip = true # ra internet (ECR, S3, CloudWatch Logs) mà không cần NAT
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.slot[each.key].arn
    container_name   = "api"
    container_port   = 8000
  }

  # Bỏ qua health check của ALB trong 120 giây đầu: task tải model từ S3 và chạy thử để numba biên dịch
  # trước khi /v1/health trả 200 (20–22 giây ở local, docs/task_sizing.md).
  health_check_grace_period_seconds = 120

  # Rolling update: task mới khoẻ rồi mới dừng task cũ; không khoẻ thì quay về bản trước.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # apply chỉ xong khi service đã ổn định (task khoẻ trong target group).
  wait_for_steady_state = true

  depends_on = [aws_lb_listener.http]
}
