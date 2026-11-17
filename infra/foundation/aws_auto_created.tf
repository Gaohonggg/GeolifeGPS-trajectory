# Tài nguyên mặc định mà AWS tạo kèm VPC: route table chính, network ACL mặc định, security group "default".
# Các block `aws_default_*` không tạo tài nguyên mới; chúng đưa tài nguyên có sẵn vào Terraform để đặt tên và cấu hình.
# Bỏ một block thì Terraform thôi quản lý tài nguyên đó; tài nguyên vẫn tồn tại tới khi VPC bị xoá.

# Route table chính: dùng cho private subnet, chỉ có route nội bộ VPC.
resource "aws_default_route_table" "main" {
  default_route_table_id = aws_vpc.main.default_route_table_id
  route                  = []
  tags                   = { Name = "${local.name}-private" }
}

# Security group "default": không có rule nào. Mọi tài nguyên dùng security group riêng; tài nguyên gắn vào
# group này sẽ không nhận và không gửi được traffic.
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-default-unused" }
}

# Network ACL mặc định: cho phép mọi traffic; việc lọc do security group đảm nhận.
resource "aws_default_network_acl" "main" {
  default_network_acl_id = aws_vpc.main.default_network_acl_id

  ingress {
    protocol   = -1
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }
  egress {
    protocol   = -1
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }
  tags = { Name = local.name }

  # Subnet không gắn ACL riêng tự dùng ACL mặc định; AWS quản lý danh sách này.
  lifecycle { ignore_changes = [subnet_ids] }
}
