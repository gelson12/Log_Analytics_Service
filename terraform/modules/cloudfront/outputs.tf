output "domain_name" {
  description = "The CloudFront distribution domain (e.g. d1234abcd.cloudfront.net)."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  description = "CloudFront distribution ID — needed for cache invalidations."
  value       = aws_cloudfront_distribution.this.id
}
