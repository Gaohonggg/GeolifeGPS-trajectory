# Stack data: RDS PostgreSQL và task definition cho các lệnh chạy một lần (migrate, seed).
# RDS tính phí theo giờ khi chạy: stop sau mỗi phiên (make aws-db-stop). Khi stop chỉ còn phí ổ đĩa.
# Tên bucket của backend truyền lúc init: make tf-init S=data

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "data/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "geolife", Stack = "data" } }
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

locals {
  name       = "geolife"
  foundation = data.terraform_remote_state.foundation.outputs
}
