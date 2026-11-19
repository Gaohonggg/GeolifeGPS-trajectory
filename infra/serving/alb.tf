# ALB công khai ở 2 public subnet, chỉ nhận cổng 80 từ allowed_cidr.
# Mỗi slot một target group. Listener chia traffic theo trọng số (local.weights); request có header X-Canary: 1
# luôn tới other_slot, để gọi thử version mới khi canary_weight còn bằng 0.

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = local.foundation.alb_security_group_id
  cidr_ipv4         = var.allowed_cidr
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_lb" "api" {
  name               = "${local.name}-api"
  load_balancer_type = "application"
  internal           = false
  subnets            = local.foundation.public_subnet_ids
  security_groups    = [local.foundation.alb_security_group_id]
  idle_timeout       = 60
}

resource "aws_lb_target_group" "slot" {
  for_each    = toset(["blue", "green"])
  name        = "${local.name}-api-${each.key}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = local.foundation.vpc_id

  # Thời gian task đang dừng được trả nốt request đang xử lý (mặc định 300 giây);
  # 30 giây dài hơn request nặng nhất đo được (docs/task_sizing.md).
  deregistration_delay = 30

  # /v1/health kiểm cả model đã nạp lẫn kết nối DB; trả 503 khi chưa sẵn sàng.
  health_check {
    path                = "/v1/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "forward"
    forward {
      dynamic "target_group" {
        for_each = aws_lb_target_group.slot
        content {
          arn    = target_group.value.arn
          weight = local.weights[target_group.key]
        }
      }
    }
  }
}

resource "aws_lb_listener_rule" "canary_header" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  condition {
    http_header {
      http_header_name = "X-Canary"
      values           = ["1"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.slot[local.other_slot].arn
  }
}
