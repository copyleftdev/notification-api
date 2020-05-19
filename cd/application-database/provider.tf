provider "aws" {
  region = "us-east-2"

  assume_role {
    role_arn = "arn:aws:iam::437518843863:role/notification-deploy-role"
  }
}

terraform {
  backend "s3" {
    bucket  = "terraform-notification-test"
    key     = "notification-api-dev-db.tfstate"
    region  = "us-east-2"
    encrypt = true
  }
}