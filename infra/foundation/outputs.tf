# Output dùng cho các stack khác (data, serving) qua terraform_remote_state.

output "region" { value = var.region }
output "account_id" { value = local.account_id }

output "vpc_id" { value = aws_vpc.main.id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }

output "alb_security_group_id" { value = aws_security_group.alb.id }
output "task_security_group_id" { value = aws_security_group.task.id }
output "rds_security_group_id" { value = aws_security_group.rds.id }

output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }

output "execution_role_arn" { value = aws_iam_role.execution.arn }
output "task_role_arn" { value = aws_iam_role.task.arn }

output "ecs_cluster_name" { value = aws_ecs_cluster.main.name }
output "ecs_cluster_arn" { value = aws_ecs_cluster.main.arn }
output "log_group_name" { value = aws_cloudwatch_log_group.ecs.name }
