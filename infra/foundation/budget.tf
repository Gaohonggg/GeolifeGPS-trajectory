# Budget tháng: email khi chi phí thực tế vượt 50% và 100% ngân sách.
# include_credit = false: tính chi phí trước khi trừ credit, nếu không budget luôn báo 0 khi tài khoản còn credit.
# Budget chỉ gửi email, không dừng tài nguyên; số liệu chi phí trễ khoảng một ngày.

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
