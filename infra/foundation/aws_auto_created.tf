# ===== Phần râu ria: những thứ AWS TỰ TẠO, dự án chỉ nhận quản lý =====
#
# File này không tạo resource nào. Khi tạo VPC `geolife` (network.tf), AWS tự sinh kèm ba thứ không có tên:
# route table chính, network ACL mặc định, security group "default". Các block `aws_default_*` dưới đây chỉ
# "nhận" chúng vào Terraform để đặt tên cho dễ nhận trên console và khoá security group "default" lại.
# Xoá file này thì Terraform bỏ quản lý, chúng vẫn còn trên AWS (AWS không cho xoá chúng khi VPC còn).
#
# Không nằm ở đây: default VPC 172.31.0.0/16 (cùng 3 subnet, IGW, route table… không tên) do AWS tạo sẵn cho mỗi
# region khi mở tài khoản; dự án không dùng và không quản lý nó.

# route table chính: private subnet dùng nó, chỉ có route nội bộ
resource "aws_default_route_table" "main" {
  default_route_table_id = aws_vpc.main.default_route_table_id
  route                  = []
  tags                   = { Name = "${local.name}-private" }
}

# security group "default" của VPC: bỏ mọi rule (mặc định nó cho các thành viên nói chuyện với nhau và ra mọi nơi).
# Không resource nào dùng nó; resource gắn nhầm vào sẽ không có đường mạng nào.
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-default-unused" }
}

# network ACL mặc định: giữ nguyên rule cho phép tất cả (lọc bằng security group), chỉ đặt tên
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

  # subnet nào không gắn ACL riêng thì tự dùng ACL mặc định; không để Terraform quản lý danh sách này
  lifecycle { ignore_changes = [subnet_ids] }
}
