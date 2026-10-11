variable "project_id" {
  type        = string
  default     = "ice-spark-build"
  description = "GCP project id."
}

variable "region" {
  type        = string
  default     = "asia-south1"
  description = "GCP region (Mumbai, closest to users)."
}

variable "backend_image" {
  type        = string
  default     = "gcr.io/cloudrun/hello"
  description = "Backend image; placeholder until cd.yml pushes the real build."
}

variable "frontend_image" {
  type        = string
  default     = "gcr.io/cloudrun/hello"
  description = "Frontend image; placeholder until cd.yml pushes the real build."
}
