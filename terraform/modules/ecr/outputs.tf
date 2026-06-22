output "repository_url" {
  description = "ECR repository URL used for docker push and task definition image URI."
  value       = aws_ecr_repository.this.repository_url
}
