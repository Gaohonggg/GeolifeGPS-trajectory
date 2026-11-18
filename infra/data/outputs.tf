# Output dùng cho stack serving và scripts/ecs_run.py.

output "db_identifier" { value = aws_db_instance.main.identifier }
output "db_host" { value = aws_db_instance.main.address }
output "db_port" { value = aws_db_instance.main.port }
output "db_name" { value = aws_db_instance.main.db_name }
output "db_user" { value = aws_db_instance.main.username }
output "db_secret_arn" { value = aws_db_instance.main.master_user_secret[0].secret_arn }

output "ops_task_definition_arn" { value = aws_ecs_task_definition.ops.arn }
output "ops_image" { value = local.image }
