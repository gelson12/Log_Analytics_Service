output "cloudfront_domain" {
  description = "Public CloudFront URL for the service."
  value       = module.cloudfront.domain_name
}

output "alb_dns_name" {
  description = "Internal ALB DNS (not publicly routable — use CloudFront)."
  value       = module.ecs.alb_dns_name
}

output "ecr_repository_url" {
  description = "ECR repository URL for docker push."
  value       = module.ecr.repository_url
}
