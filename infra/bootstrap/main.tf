# Stack bootstrap: bucket chứa Terraform state của các stack khác. Tạo một lần.
# State của stack này nằm ở local vì bucket chưa tồn tại lúc tạo. Nếu mất file state, nhập lại bằng:
#   terraform -chdir=infra/bootstrap import aws_s3_bucket.state geolife-<account_id>-tfstate

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "region" {
  type    = string
  default = "ap-southeast-1"
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "geolife", Stack = "bootstrap" } }
}

data "aws_caller_identity" "me" {}

resource "aws_s3_bucket" "state" {
  bucket = "geolife-${data.aws_caller_identity.me.account_id}-tfstate"
}

# Versioning cho phép khôi phục state về bản trước khi state hỏng hoặc bị ghi nhầm.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 90 }
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}
