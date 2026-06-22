variable "name" {
  description = "Service name, used in the distribution comment."
  type        = string
}

variable "environment" {
  description = "Deployment environment (prod, staging …)."
  type        = string
}

variable "alb_dns_name" {
  description = "DNS name of the ALB to use as the CloudFront origin."
  type        = string
}
