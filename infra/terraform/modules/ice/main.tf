# ICE environment module (UAT): Artifact Registry, Cloud SQL (public IP, PITR),
# backend + frontend Cloud Run services, runtime SA + secret bindings.
#
# FREE-TIER NOTE (UAT): this module deliberately uses NO VPC connector, NO
# private services networking, and NO Memorystore — all three cost $25+/mo each
# with no free tier. The app has zero Redis references, and Cloud Run reaches
# the public-IP Cloud SQL instance directly (SSL enforced by the driver +
# strong managed password). A production env would re-add private networking
# (see docs/GCP_DEPLOY.md §9).

# Enable the APIs this module needs (idempotent; disable_on_destroy=false so a
# `terraform destroy` never bricks the project for other workloads).
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "ice-${var.env}"
  format        = "DOCKER"
  description   = "ICE backend + frontend images (${var.env})."

  depends_on = [google_project_service.apis]
}

# Cloud SQL PG16 — PUBLIC IP for free-tier UAT (no connector cost), PITR +
# daily automated backups BEFORE any data lands. Access is guarded by a strong
# managed password + authorized-network scoping (see below); the asyncpg
# driver negotiates TLS to the instance.
resource "google_sql_database_instance" "db" {
  name                = "ice-${var.env}-db"
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true

  depends_on = [google_project_service.apis]

  settings {
    tier = var.db_tier
    # ENTERPRISE (not PLUS): shared-core micro tiers like db-f1-micro only
    # exist on ENTERPRISE. Provider v6 defaults to ENTERPRISE_PLUS, which
    # rejects them — this line is the free-tier-compatible choice.
    edition           = "ENTERPRISE"
    availability_type = "ZONAL" # UAT: zonal (prod would be REGIONAL)
    disk_autoresize   = true
    disk_size         = 10 # GB — stay at the minimum for UAT

    ip_configuration {
      # UAT-only: open to the internet so serverless Cloud Run (no connector)
      # and the operator's machine can reach it. The password is a 24-byte
      # random secret in Secret Manager; tighten to Cloud Run egress ranges or
      # move to private IP before any production use.
      ipv4_enabled = true
      authorized_networks {
        name  = "uat-demo-open"
        value = "0.0.0.0/0"
      }
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 7
      }
    }
  }
}

resource "google_sql_database" "app" {
  project  = var.project_id
  instance = google_sql_database_instance.db.name
  name     = var.db_name
}

resource "google_sql_user" "app" {
  project  = var.project_id
  instance = google_sql_database_instance.db.name
  name     = var.db_user
  # Password is operator-managed: set once via console/gcloud after apply and
  # stored as uat-POSTGRES_PASSWORD in Secret Manager (never in tfvars/state).
  # Changing it here would write it to state — intentionally left unmanaged.
  password = "__MANAGED_OUTSIDE_TERRAFORM__"
  lifecycle {
    ignore_changes = [password]
  }
}

# Runtime service account (least privilege: SQL client + secret accessor).
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "ice-${var.env}-runtime"
  display_name = "ICE ${var.env} Cloud Run runtime"
}

resource "google_project_iam_member" "runtime_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_secrets" {
  for_each = toset([var.secret_key_secret_id, var.postgres_password_secret_id])
  project  = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# Backend — FastAPI (existing backend/Dockerfile: non-root, gunicorn, $PORT, /health).
# NOTE: PORT is NOT set here — Cloud Run reserves it and injects it automatically
# (the image defaults to 8080 when PORT is unset, which matches container_port).
# Migrations run as an explicit CD step, NOT at boot: ICE_RUN_MIGRATIONS=false
# keeps entrypoint.sh migration+seed dev-only in UAT.
resource "google_cloud_run_v2_service" "backend" {
  project  = var.project_id
  name     = "ice-backend-${var.env}"
  location = var.region

  depends_on = [google_project_service.apis]

  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2 # UAT demo traffic; raise for load tests
    }
    containers {
      image = var.backend_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          # 4 gunicorn workers each import the full app (incl. langchain
          # stack): needs headroom. Billed on use; min-instances 0 keeps
          # idle demo cost inside the free quota.
          cpu    = "2"
          memory = "2Gi"
        }
      }
      env {
        name  = "ENVIRONMENT"
        value = var.env
      }
      env {
        name  = "ICE_RUN_MIGRATIONS"
        value = "false"
      }
      env {
        name  = "POSTGRES_SERVER"
        value = google_sql_database_instance.db.public_ip_address
      }
      env {
        name  = "POSTGRES_PORT"
        value = "5432"
      }
      env {
        name  = "POSTGRES_USER"
        value = var.db_user
      }
      env {
        name  = "POSTGRES_DB"
        value = var.db_name
      }
      env {
        name = "POSTGRES_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.postgres_password_secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = var.secret_key_secret_id
            version = "latest"
          }
        }
      }
      # No REDIS_HOST: the app has zero Redis references (config defaults to
      # localhost, unused). Memorystore arrives with P4.4 if ever needed.
      # Google OAuth disabled in UAT until a custom domain exists.
      env {
        name  = "GOOGLE_CLIENT_ID"
        value = ""
      }
      env {
        name  = "GOOGLE_CLIENT_SECRET"
        value = ""
      }
      env {
        name  = "ICE_AI_ENABLED"
        value = "false"
      }
      env {
        name  = "ICE_AI_MUTATIONS_ENABLED"
        value = "false"
      }
      env {
        name  = "BACKEND_CORS_ORIGINS"
        value = jsonencode(concat([google_cloud_run_v2_service.frontend.uri], var.allowed_cors_origins))
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Frontend — nginx static SPA (frontend/Dockerfile, listens on 8080).
# NOTE: same PORT reservation as above — not set, injected by Cloud Run.
# VITE_API_URL is baked at image build time by cd.yml.
resource "google_cloud_run_v2_service" "frontend" {
  project  = var.project_id
  name     = "ice-frontend-${var.env}"
  location = var.region

  depends_on = [google_project_service.apis]

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.frontend_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Public demo access (UAT): unauthenticated invoker on both services.
# (Production would gate the backend behind IAP/LB + auth.)
resource "google_cloud_run_v2_service_iam_member" "public_backend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "public_frontend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
