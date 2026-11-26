variable "region" {
  type    = string
  default = "ap-southeast-1"
}

# ---- Ghi bởi make aws-promote vào models.auto.tfvars.json ----

variable "latest_model_version" {
  type        = number
  description = "Registry version trong cấu hình làm việc ($LATEST) của function; Lambda đóng version mới từ cấu hình này mỗi khi nó đổi"
}

variable "live" {
  type = object({
    lambda_version = optional(number)
    model_version  = number
  })
  description = "Alias live: Lambda version nhận traffic và registry version chứa trong nó; lambda_version null: version vừa được đóng"
}

variable "challenger" {
  type = object({
    lambda_version = number
    model_version  = number
  })
  default     = null
  description = "Alias challenger: Lambda version chứa model của @challenger; null hoặc trùng live: không chia traffic"
}

# ---- Sửa tay trong canary.auto.tfvars ----

variable "canary_weight" {
  type        = number
  default     = 20
  description = "Phần trăm request của alias live chuyển sang version của challenger; 0: cắt traffic tới version mới"
  validation {
    condition     = var.canary_weight >= 0 && var.canary_weight < 100
    error_message = "canary_weight trong [0, 100): 100% sang challenger là chốt, làm bằng make aws-promote."
  }
}

# ---- Ghi bởi make aws-pause / aws-resume vào pause.auto.tfvars (không commit) ----

variable "paused" {
  type        = bool
  default     = false
  description = "true: reserved concurrency của function về 0, mọi request bị từ chối"
}

# ---- Function API ----

variable "model_name" {
  type    = string
  default = "geolife_home_office"
}

variable "data_version" {
  type        = number
  default     = 1
  description = "Bản dữ liệu điểm theo user: s3://…/data/serving/v_<n>"
}

# 2 048 MB: request lớn nhất dùng tới 1,5 GB trên Lambda; 1 769 / 3 008 MB không nhanh hơn (docs/infra/lambda/sizing.md, L7).
variable "api_memory" {
  type    = number
  default = 2048
}

# Dưới giới hạn 30 giây của API Gateway, để request quá hạn được ghi lỗi ở Lambda.
variable "api_timeout" {
  type    = number
  default = 29
}

# Trần số request chạy cùng lúc, tức trần chi phí mỗi giờ khi URL bị gọi tràn.
variable "api_reserved_concurrency" {
  type    = number
  default = 10
}

variable "api_log_retention_days" {
  type    = number
  default = 30
}

# ---- HTTP API ----

variable "throttle_rate" {
  type        = number
  default     = 10
  description = "Request mỗi giây ở stage; vượt thì API Gateway trả 429"
}

variable "throttle_burst" {
  type    = number
  default = 20
}
