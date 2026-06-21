variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Deployment environment label (prod, staging …)."
  type        = string
  default     = "prod"
}

variable "vpc_id" {
  description = "VPC in which the ECS service will run."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the ALB."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the ECS tasks."
  type        = list(string)
}

variable "log_buckets" {
  description = "S3 buckets the service is allowed to read logs from."
  type        = list(string)
}

variable "image_tag" {
  description = "Docker image tag (git SHA) to deploy."
  type        = string
  default     = "latest"
}
