variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

# gps_points chiếm 2,7 GB ở local (docs/task_sizing.md).
variable "db_allocated_storage_gb" {
  type    = number
  default = 20
}

# Image cho task chạy một lần. null: build mới nhất trong ECR.
variable "image_tag" {
  type    = string
  default = null
}
