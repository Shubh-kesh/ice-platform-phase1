# Shared inputs for the ICE environment module (instantiated once per env; today: uat only).
variable "project_id" {
  type        = string
  description = "GCP project id (ice-spark-build)."
}

variable "region" {
  type        = string
  default     = "asia-south1"
  description = "GCP region for all regional resources."
}

variable "env" {
  type        = string
  description = "Environment name (uat)."
}

variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Cloud SQL tier (shared-core micro — cheapest, UAT demo scale)."
}

variable "db_user" {
  type        = string
  default     = "ice_app"
  description = "Least-privilege app DB user (created by the module)."
}

variable "db_name" {
  type        = string
  default     = "ice_uat"
  description = "Application database name."
}

variable "backend_image" {
  type        = string
  description = "Backend container image (Artifact Registry path:tag). Placeholder on first apply; cd.yml replaces it."
}

variable "frontend_image" {
  type        = string
  description = "Frontend container image (Artifact Registry path:tag). Placeholder on first apply; cd.yml replaces it."
}

variable "secret_key_secret_id" {
  type        = string
  default     = "uat-SECRET_KEY"
  description = "Secret Manager id holding the FastAPI SECRET_KEY."
}

variable "postgres_password_secret_id" {
  type        = string
  default     = "uat-POSTGRES_PASSWORD"
  description = "Secret Manager id holding the app DB password."
}

variable "allowed_cors_origins" {
  type        = list(string)
  default     = []
  description = "Extra browser origins for BACKEND_CORS_ORIGINS (frontend Run URL is always included)."
}
