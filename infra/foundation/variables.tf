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
