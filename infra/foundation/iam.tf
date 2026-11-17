# Hai role của ECS task:
# - execution role: ECS dùng để kéo image, ghi log, đọc secret và tiêm vào container.
# - task role: code trong container dùng để gọi AWS. Đọc data/, models/, monitoring/; ghi monitoring/, exports/.
#   Không ghi được models/: chỉ người phát hành model ghi vào đó.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Mật khẩu DB do RDS sinh và lưu trong Secrets Manager, tên secret bắt đầu bằng "rds!".
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:rds!*"]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-rds-secret"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

locals {
  bucket_arn   = aws_s3_bucket.artifacts.arn
  read_prefix  = ["data/", "models/", "monitoring/"]
  write_prefix = ["monitoring/", "exports/"]
}

data "aws_iam_policy_document" "task_s3" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [local.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = flatten([for p in local.read_prefix : [p, "${p}*"]])
    }
  }
  statement {
    sid       = "Read"
    actions   = ["s3:GetObject"]
    resources = [for p in local.read_prefix : "${local.bucket_arn}/${p}*"]
  }
  statement {
    sid       = "Write"
    actions   = ["s3:PutObject"]
    resources = [for p in local.write_prefix : "${local.bucket_arn}/${p}*"]
  }
}

resource "aws_iam_role_policy" "task_s3" {
  name   = "artifacts-bucket"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_s3.json
}
