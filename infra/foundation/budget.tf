# Cảnh báo chi phí: một budget tháng, email khi chi phí thực tế chạm 50% và 100%.
# include_credit = false: mặc định budget tính sau khi trừ credit, còn credit thì luôn báo 0.
# Budget chỉ gửi email, không dừng resource nào; số liệu trễ khoảng một ngày.

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = [50, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
