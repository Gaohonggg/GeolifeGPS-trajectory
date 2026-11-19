# Stack serving: ALB và hai slot API (blue / green), mỗi slot là một ECS service chạy một model version.
# ALB và task tính phí theo giờ: destroy sau mỗi phiên (make aws-down), dựng lại bằng make aws-up.
# Version của từng slot, live slot và canary_weight nằm trong models.auto.tfvars.json, do make aws-promote ghi.
# Tên bucket của backend truyền lúc init: make tf-init S=serving

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "serving/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { Project = "geolife", Stack = "serving" } }
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

data "terraform_remote_state" "data" {
  backend = "s3"
  config = {
    bucket = "geolife-${data.aws_caller_identity.me.account_id}-tfstate"
    key    = "data/terraform.tfstate"
    region = var.region
  }
}

locals {
  name       = "geolife"
  foundation = data.terraform_remote_state.foundation.outputs
  db         = data.terraform_remote_state.data.outputs

  # Slot không phục vụ @champion: nơi chạy @challenger khi có canary.
  other_slot = var.live_slot == "blue" ? "green" : "blue"
  # Chỉ slot có version mới có task definition và service.
  slot_versions = { blue = var.blue_model_version, green = var.green_model_version }
  active_slots  = { for slot, v in local.slot_versions : slot => v if v != null }

  # Phần trăm traffic của listener: live slot nhận 100 - canary_weight, slot còn lại nhận canary_weight.
  weights = {
    (var.live_slot)    = 100 - var.canary_weight
    (local.other_slot) = var.canary_weight
  }
}
