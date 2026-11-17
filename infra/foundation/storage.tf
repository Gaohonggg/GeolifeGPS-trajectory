# Bucket artifacts (Plan mục 3.2): data/preprocess, models/<model>/v=<n>/, monitoring/, exports/.
# Mọi thứ gắn với số version, không có alias. Không có lifecycle xoá models/.

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

  # bản cũ của object (bị ghi đè hoặc xoá) giữ 30 ngày
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
  # tag là git SHA: một tag chỉ trỏ vào một image
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # make aws-nuke xoá được cả repo còn image
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "giu 5 image gan nhat"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}
