# Stack foundation: tài nguyên dùng chung, luôn bật: bucket artifacts, ECR, budget.
# Không có tài nguyên tính phí theo giờ.
# Tên bucket của backend truyền lúc init: make tf-init S=foundation

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
