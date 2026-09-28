terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  # Local state for review and `terraform plan`. For a shared environment, switch to an
  # S3 backend with a DynamoDB lock table.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "sentinel-ai"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name = "sentinel-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}
