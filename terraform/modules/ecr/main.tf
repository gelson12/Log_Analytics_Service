################################################################################
# modules/ecr — Elastic Container Registry
################################################################################

resource "aws_ecr_repository" "this" {
  name                 = "${var.name}-${var.environment}"
  image_tag_mutability = "IMMUTABLE"   # prevent overwriting a deployed SHA

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Keep the last 30 images to avoid runaway storage costs
resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 30 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

output "repository_url" {
  value = aws_ecr_repository.this.repository_url
}
