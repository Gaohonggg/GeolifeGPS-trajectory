# Bucket artifacts. Bố cục:
#   data/preprocess/v_<n>/            output của preprocess, nguồn để seed RDS
#   models/<model>/v=<n>/             bản phát hành bất biến của model version n (geolife.publish)
#   monitoring/, exports/             baseline drift, log dự đoán xuất ra
# Mọi đường dẫn gắn với số version; vai trò của version (alias) chỉ nằm trên registry.
# Không có rule xoá models/: version đã phát hành luôn còn để rollback.

resource "aws_s3_bucket" "artifacts" {
  bucket = "${local.name}-${local.account_id}-artifacts"
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_policy" "artifacts_tls_only" {
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  # Bản cũ của object (bị ghi đè hoặc xoá) giữ 30 ngày.
  rule {
    id     = "noncurrent-30d"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }

  rule {
    id     = "exports-90d"
    status = "Enabled"
    filter { prefix = "exports/" }
    expiration { days = 90 }
  }

  depends_on = [aws_s3_bucket_versioning.artifacts]
}

# ---- ECR ----

resource "aws_ecr_repository" "api" {
  name = "${local.name}-api"
  # Tag là git SHA; không ghi đè được tag đã có.
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # cho phép destroy repo khi còn image
  image_scanning_configuration { scan_on_push = true }
}

# Giữ 5 build gần nhất. Mỗi build có đúng một tag (git SHA), nên rule đếm image có tag. Manifest không tag
# (manifest con của một OCI index) không được tính là build; ECR không xoá chúng khi index còn tham chiếu.
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "giu 5 build gan nhat"
        selection    = { tagStatus = "tagged", tagPatternList = ["*"], countType = "imageCountMoreThan", countNumber = 5 }
        action       = { type = "expire" }
      },
      {
        # Manifest không tag còn lại sau khi index của nó hết hạn.
        rulePriority = 2
        description  = "don manifest khong tag sau 7 ngay"
        selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
        action       = { type = "expire" }
      },
    ]
  })
}
