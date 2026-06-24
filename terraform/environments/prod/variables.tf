variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "prod"
}

variable "log_buckets" {
  description = "S3 buckets the service is allowed to read logs from."
  type        = list(string)
  default     = ["base-platform-logs-s3-22-06"]
}

variable "image_tag" {
  description = "Docker image tag (git SHA) to deploy."
  type        = string
  default     = "latest"
}
