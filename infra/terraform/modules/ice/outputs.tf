output "backend_url" {
  value       = google_cloud_run_v2_service.backend.uri
  description = "Public backend URL (VITE_API_URL base for the frontend build)."
}

output "frontend_url" {
  value       = google_cloud_run_v2_service.frontend.uri
  description = "Public UAT demo URL to hand to the client."
}

output "db_public_ip" {
  value       = google_sql_database_instance.db.public_ip_address
  description = "Cloud SQL public IP (UAT free-tier tradeoff; password + TLS guarded)."
  sensitive   = true
}

output "artifact_registry" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
  description = "Image repo prefix used by cd.yml."
}
