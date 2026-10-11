# UAT tfvars — non-secret config only. Secrets live in Secret Manager
# (uat-SECRET_KEY, uat-POSTGRES_PASSWORD) and are never written here.
project_id = "ice-spark-build"
region     = "asia-south1"

# First apply only: placeholder images; cd.yml deploys real builds after.
backend_image  = "asia-south1-docker.pkg.dev/ice-spark-build/ice-uat/ice-backend:uat-1"
frontend_image = "asia-south1-docker.pkg.dev/ice-spark-build/ice-uat/ice-frontend:uat-1"
