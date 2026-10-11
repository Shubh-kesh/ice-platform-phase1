# UAT environment — the ONLY environment (staging/prod deferred by owner decision).
terraform {
  backend "gcs" {
    # Bucket created once per docs/GCP_DEPLOY.md §2 (ice-spark-build-tfstate).
    prefix = "ice/uat"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "ice_uat" {
  source = "../../modules/ice"

  project_id     = var.project_id
  region         = var.region
  env            = "uat"
  backend_image  = var.backend_image
  frontend_image = var.frontend_image
  # Cloud Run serves each service under two hostnames (the stable
  # "<name>-<hash>.a.run.app" URL and the numbered
  # "<name>-<project-number>.<region>.run.app" URL). Both must pass CORS
  # because the client may open either one in the browser.
  allowed_cors_origins = [
    "https://ice-backend-uat-386147112888.asia-south1.run.app",
    "https://ice-frontend-uat-386147112888.asia-south1.run.app",
  ]
}

output "backend_url" {
  value = module.ice_uat.backend_url
}

output "frontend_url" {
  value = module.ice_uat.frontend_url
}

output "artifact_registry" {
  value = module.ice_uat.artifact_registry
}
