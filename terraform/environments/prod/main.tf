################################################################################
# environments/prod/main.tf
################################################################################

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "log-analytics-tfstate-950916120579"
    key            = "prod/terraform.tfstate"
    region         = "eu-west-1"
    encrypt        = true
    dynamodb_table = "log-analytics-tfstate-lock"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "log-analytics"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

################################################################################
# VPC — creates networking from scratch (no default VPC in this account)
################################################################################

module "vpc" {
  source = "../../modules/vpc"

  name        = "log-analytics"
  environment = var.environment
}

################################################################################
# ECR
################################################################################

module "ecr" {
  source = "../../modules/ecr"

  name        = "log-analytics"
  environment = var.environment
}

################################################################################
# IAM
################################################################################

module "iam" {
  source = "../../modules/iam"

  name        = "log-analytics"
  environment = var.environment
  log_buckets = var.log_buckets
  aws_region  = var.aws_region
  account_id  = data.aws_caller_identity.current.account_id
}

################################################################################
# ECS Fargate + ALB
################################################################################

module "ecs" {
  source = "../../modules/ecs"

  name               = "log-analytics"
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  private_subnet_ids = module.vpc.private_subnet_ids

  ecr_image_uri           = "${module.ecr.repository_url}:${var.image_tag}"
  task_execution_role_arn = module.iam.task_execution_role_arn
  task_role_arn           = module.iam.task_role_arn

  container_port = 8000
  cpu            = 256
  memory         = 512
  desired_count  = 2
  log_bucket     = var.log_buckets[0]
  git_sha        = var.image_tag
}

################################################################################
# CloudFront
################################################################################

module "cloudfront" {
  source = "../../modules/cloudfront"

  name         = "log-analytics"
  environment  = var.environment
  alb_dns_name = module.ecs.alb_dns_name
}
