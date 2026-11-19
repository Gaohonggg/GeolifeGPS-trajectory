# RDS PostgreSQL ở 2 private subnet, chỉ nhận kết nối từ security group của task.
# Mật khẩu do RDS sinh và lưu trong Secrets Manager (manage_master_user_password), không nằm trong state.

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = local.foundation.private_subnet_ids
}

# random_page_cost mặc định 4 giả định ổ quay; gp3 là SSD nên đọc ngẫu nhiên gần bằng đọc tuần tự.
# (docs/task_sizing.md, B5). Đổi parameter group của instance chỉ có hiệu lực sau khi reboot hoặc stop / start.
resource "aws_db_parameter_group" "main" {
  name   = local.name
  family = "postgres17"

  parameter {
    name  = "random_page_cost"
    value = "1.1"
  }
}

resource "aws_db_instance" "main" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "17" # cùng major với postgres:17 ở local; minor do AWS chọn và tự nâng
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name                     = local.name
  username                    = local.name
  manage_master_user_password = true

  parameter_group_name   = aws_db_parameter_group.main.name
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [local.foundation.rds_security_group_id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period    = 1
  skip_final_snapshot        = true
  deletion_protection        = false
  auto_minor_version_upgrade = true
  apply_immediately          = true

  # Performance Insights và Enhanced Monitoring tắt: metric cơ bản của RDS trong CloudWatch là đủ.
  performance_insights_enabled = false
  monitoring_interval          = 0
}
