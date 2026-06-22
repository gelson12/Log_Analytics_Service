################################################################################
# infra/bootstrap.tf
#
# Run ONCE manually before anything else:
#   cd infra
#   terraform init
#   terraform apply
#
# Creates the S3 bucket + DynamoDB table for Terraform remote state.
# Uses local state (no chicken-and-egg problem).
################################################################################

terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region"   { default = "eu-west-1" }
variable "state_bucket" { default = "log-analytics-tfstate-206453958024" }
variable "lock_table"   { default = "log-analytics-tfstate-lock" }

resource "aws_s3_bucket" "tfstate" {
  bucket        = var.state_bucket
  force_destroy = false
  tags          = { Name = "Terraform state — log-analytics" }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "lock" {
  name         = var.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  tags = { Name = "Terraform state lock — log-analytics" }
}

output "state_bucket" { value = aws_s3_bucket.tfstate.bucket }
output "lock_table"   { value = aws_dynamodb_table.lock.name }
