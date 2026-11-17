variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "alert_email" {
  type        = string
  description = "Email nhận cảnh báo chi phí (đặt trong terraform.tfvars, không commit)"
}

variable "monthly_budget_usd" {
  type        = number
  default     = 20
  description = "Ngân sách tháng; email khi chi phí thực tế chạm 50% và 100%"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "log_retention_days" {
  type    = number
  default = 14
}
