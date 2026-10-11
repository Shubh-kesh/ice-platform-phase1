# ICE platform — UAT on GCP (Terraform)
# Project: ice-spark-build. Single environment: uat.
# State: GCS backend (bucket configured per-environment, see environments/uat/backend.tf).

terraform {
  required_version = ">= 1.9.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}
