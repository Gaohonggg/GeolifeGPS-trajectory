# Output dùng cho các stack khác qua terraform_remote_state.

output "region" { value = var.region }
output "account_id" { value = local.account_id }

output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "artifacts_bucket_arn" { value = aws_s3_bucket.artifacts.arn }
output "ecr_repository_url" { value = aws_ecr_repository.api.repository_url }
