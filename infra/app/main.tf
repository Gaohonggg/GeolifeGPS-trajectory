# Stack app: function Lambda của API, alias live / challenger, HTTP API.
# Khi không có request thì không thành phần nào tính tiền; stack giữ nguyên giữa các phiên.
# Model của từng alias nằm trong models.auto.tfvars.json, do make aws-promote ghi.
# Tên bucket của backend truyền lúc init: make tf-init S=app

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "app/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "geolife", Stack = "app" } }
}

data "aws_caller_identity" "me" {}

data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = "geolife-${data.aws_caller_identity.me.account_id}-tfstate"
    key    = "foundation/terraform.tfstate"
    region = var.region
  }
}

# Image mới nhất trong ECR. Ghim theo digest: mỗi Lambda version ghi đúng một image.
data "aws_ecr_image" "api" {
  repository_name = split("/", local.foundation.ecr_repository_url)[1]
  most_recent     = true
}

locals {
  name       = "geolife"
  foundation = data.terraform_remote_state.foundation.outputs
  bucket     = local.foundation.artifacts_bucket
  image      = "${local.foundation.ecr_repository_url}@${data.aws_ecr_image.api.image_digest}"

  # Bản phát hành bất biến của một registry version (geolife.publish); function không gọi registry.
  model_prefix = "models/${var.model_name}"
  points_uri   = "s3://${local.bucket}/data/serving/v_${var.data_version}"
}
