variable "region" {
  type    = string
  default = "ap-southeast-1"
}

# IP được gọi ALB, dạng CIDR. make aws-up truyền IP hiện tại của máy chạy lệnh (/32).
variable "allowed_cidr" {
  type = string
}

# ---- Ghi bởi make aws-promote vào models.auto.tfvars.json ----

variable "blue_model_version" {
  type        = number
  default     = null
  description = "Model version trong registry mà slot blue nạp; null: slot không chạy"
}

variable "green_model_version" {
  type        = number
  default     = null
  description = "Model version trong registry mà slot green nạp; null: slot không chạy"
}

variable "live_slot" {
  type        = string
  default     = "blue"
  description = "Slot đang phục vụ @champion"
  validation {
    condition     = contains(["blue", "green"], var.live_slot)
    error_message = "live_slot là blue hoặc green."
  }
}

variable "canary_weight" {
  type        = number
  default     = 0
  description = "Phần trăm traffic tới slot không phải live slot"
  validation {
    condition     = var.canary_weight >= 0 && var.canary_weight <= 100
    error_message = "canary_weight trong khoảng 0–100."
  }
}

# ---- Task API ----

variable "image_tag" {
  type        = string
  default     = null
  description = "Tag của image trong ECR; null: build mới nhất"
}

variable "model_name" {
  type    = string
  default = "geolife_home_office"
}

# 0,5 vCPU / 2 GB: 2 GB chứa được request lớn nhất khi chạy một mình (docs/task_sizing.md, B3).
variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 2048
}
