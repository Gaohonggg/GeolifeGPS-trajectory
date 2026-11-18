# Task definition cho các lệnh chạy một lần trong VPC (migrate, seed, kiểm tra DB).
# Lệnh truyền lúc chạy qua command override: scripts/ecs_run.py.

data "aws_ecr_image" "api" {
  repository_name = split("/", local.foundation.ecr_repository_url)[1]
  image_tag       = var.image_tag
  most_recent     = var.image_tag == null ? true : null
}

locals {
  # Ghim theo digest: task definition luôn trỏ đúng một image.
  image = "${local.foundation.ecr_repository_url}@${data.aws_ecr_image.api.image_digest}"
}

resource "aws_ecs_task_definition" "ops" {
  family                   = "${local.name}-ops"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = local.foundation.execution_role_arn
  task_role_arn            = local.foundation.task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "ops"
    image     = local.image
    essential = true
    command   = ["python", "-m", "geolife_api.migrate"]
    environment = [
      { name = "DB_HOST", value = aws_db_instance.main.address },
      { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
      { name = "DB_NAME", value = aws_db_instance.main.db_name },
      { name = "DB_USER", value = aws_db_instance.main.username },
      { name = "AWS_REGION", value = var.region },
    ]
    secrets = [
      # Secret do RDS quản lý là JSON {"username", "password"}; ECS lấy riêng khoá password.
      { name = "DB_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = local.foundation.log_group_name
        awslogs-region        = var.region
        awslogs-stream-prefix = "ops"
      }
    }
  }])
}
