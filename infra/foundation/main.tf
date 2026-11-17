# Nền luôn bật, gần như 0 đồng: mạng, bucket artifacts, ECR, IAM role của task, ECS cluster, log group, budget.
# Không có resource nào tính tiền theo giờ (không NAT, không ALB, không RDS).
# Bucket của backend truyền lúc init: make tf-init S=foundation

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "foundation/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "geolife", Stack = "foundation" } }
}

data "aws_caller_identity" "me" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.me.account_id
  name       = "geolife"
}
