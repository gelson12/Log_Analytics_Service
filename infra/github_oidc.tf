################################################################################
# infra/github_oidc.tf
#
# Creates the IAM OIDC provider for GitHub Actions and an IAM role the CD
# workflow can assume via OIDC — no long-lived AWS_ACCESS_KEY_ID needed.
#
# Run once, in the same apply as bootstrap.tf:
#   cd infra && terraform apply
#
# Then set the output role ARN as the AWS_DEPLOY_ROLE_ARN repository secret.
################################################################################

variable "github_org"  { description = "Your GitHub org or username" }
variable "github_repo" { description = "Repository name (e.g. log-analytics)" }

locals {
  github_oidc_url = "https://token.actions.githubusercontent.com"
  # Thumbprint for GitHub's OIDC token endpoint (stable, published by GitHub)
  github_thumbprint = "6938fd4d98bab03faadb97b34396831e3780aea1"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = local.github_oidc_url
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [local.github_thumbprint]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only the main branch of your repo can assume this role
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "github-actions-log-analytics-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
  description        = "Assumed by GitHub Actions CD workflow via OIDC"
}

# Permissions the deploy role needs:
# ECR push, ECS update, Terraform state (S3 + DynamoDB), plus the ability to
# create/update the resources Terraform manages (IAM, ECS, ALB, CloudFront …).
# In a real org you'd tighten this further; AdministratorAccess is used here
# for simplicity — restrict to your actual resource types once stable.
resource "aws_iam_role_policy_attachment" "github_deploy_admin" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "deploy_role_arn" {
  description = "Set this as the AWS_DEPLOY_ROLE_ARN GitHub Actions secret."
  value       = aws_iam_role.github_deploy.arn
}
