#!/usr/bin/env bash
set -euo pipefail
set +x

# Run from any directory. Never print API keys.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [--check]
Required: GCP_PROJECT_ID, OPENAI_API_KEY, TAVILY_API_KEY
Optional: GCP_REGION (us-west1), AR_REPOSITORY (hw1),
          CLOUD_RUN_SERVICE (hw1-agent), OPENAI_MODEL (gpt-5), IMAGE_TAG
          EXISTING_IMAGE_URI (skip building and deploy this image)
Keys may be loaded from the local .env file (shell KEY=value format).
--check validates local settings only. It makes no cloud changes.
EOF
}

CHECK_ONLY=false
case "${1:-}" in
  --check) CHECK_ONLY=true ;;
  --help|-h) usage; exit 0 ;;
  '') ;;
  *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi

# Preserve exported values when loading the local development file.
saved_openai="${OPENAI_API_KEY:-}"
saved_tavily="${TAVILY_API_KEY:-}"
saved_model="${OPENAI_MODEL:-}"
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
OPENAI_API_KEY="${saved_openai:-${OPENAI_API_KEY:-}}"
TAVILY_API_KEY="${saved_tavily:-${TAVILY_API_KEY:-}}"
OPENAI_MODEL="${saved_model:-${OPENAI_MODEL:-gpt-5}}"

for name in GCP_PROJECT_ID OPENAI_API_KEY TAVILY_API_KEY; do
  if [[ -z "${!name:-}" || "${!name}" == *your_* || "${!name}" == *replace_with* ]]; then
    printf 'Set a real value for %s before deploying.\n' "$name" >&2
    exit 1
  fi
done
command -v gcloud >/dev/null || { echo 'Install the Google Cloud CLI first.' >&2; exit 1; }
GCP_REGION="${GCP_REGION:-us-west1}"
AR_REPOSITORY="${AR_REPOSITORY:-hw1}"
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-hw1-agent}"
IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
IMAGE_URI="${EXISTING_IMAGE_URI:-${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${AR_REPOSITORY}/${CLOUD_RUN_SERVICE}:${IMAGE_TAG}}"

# The alternate delimiter supports commas in values without splitting them.
for value in "$OPENAI_API_KEY" "$TAVILY_API_KEY" "$OPENAI_MODEL"; do
  if [[ "$value" == *'|'* || "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo 'Runtime values must not contain pipes or newlines.' >&2
    exit 1
  fi
done
printf 'Project: %s\nRegion: %s\nService: %s\nImage: %s\n' \
  "$GCP_PROJECT_ID" "$GCP_REGION" "$CLOUD_RUN_SERVICE" "$IMAGE_URI"
if "$CHECK_ONLY"; then
  echo 'Local checks passed. No cloud requests were made.'
  exit 0
fi

if [[ -z "$(gcloud auth list --filter=status:ACTIVE --format='value(account)')" ]]; then
  echo 'Run gcloud auth login first.' >&2
  exit 1
fi

if [[ -z "${EXISTING_IMAGE_URI:-}" ]]; then
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com --project="$GCP_PROJECT_ID" --quiet

  if ! gcloud artifacts repositories describe "$AR_REPOSITORY" \
    --location="$GCP_REGION" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud artifacts repositories create "$AR_REPOSITORY" \
      --repository-format=docker --location="$GCP_REGION" \
      --project="$GCP_PROJECT_ID" --quiet
  fi

  # Cloud Build builds and pushes the image. The upload allowlist excludes .env.
  gcloud builds submit . --tag="$IMAGE_URI" --ignore-file=.gcloudignore \
    --project="$GCP_PROJECT_ID" --quiet --suppress-logs
else
  echo "Using the existing image; skipping build."
fi

# Keep existing Secret Manager references when updating a service.
existing_service="$(gcloud run services list --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" --filter="metadata.name=${CLOUD_RUN_SERVICE}" \
  --format='value(metadata.name)')"
secret_vars=""
if [[ -n "$existing_service" ]]; then
  secret_vars="$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
    --flatten='spec.template.spec.containers[].env[]' \
    --format='csv[no-heading](spec.template.spec.containers.env.name,spec.template.spec.containers.env.valueFrom.secretKeyRef.name)')"
fi
runtime_env="^|^OPENAI_MODEL=${OPENAI_MODEL}"
for name in OPENAI_API_KEY TAVILY_API_KEY; do
  has_secret=false
  while IFS=, read -r env_name secret_name; do
    if [[ "$env_name" == "$name" && -n "$secret_name" ]]; then
      has_secret=true
    fi
  done <<< "$secret_vars"
  if "$has_secret"; then
    printf 'Keeping the existing Secret Manager reference for %s.\n' "$name"
  else
    runtime_env+="|${name}=${!name}"
  fi
done

gcloud run deploy "$CLOUD_RUN_SERVICE" --image="$IMAGE_URI" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --platform=managed \
  --allow-unauthenticated --port=8080 --memory=1Gi --cpu=1 \
  --min=0 --max=1 --min-instances=0 --max-instances=1 --timeout=900 \
  --update-env-vars="$runtime_env" \
  --quiet

SERVICE_URL="$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
  --region="$GCP_REGION" --project="$GCP_PROJECT_ID" --format='value(status.url)')"
if [[ -z "$SERVICE_URL" ]]; then
  echo 'Deployment returned no service URL. Check Cloud Run in the console.' >&2
  exit 1
fi
printf '\nService: %s\nAPI docs: %s/docs\nHealth: %s/health\nFiles: %s/files\n' \
  "$SERVICE_URL" "$SERVICE_URL" "$SERVICE_URL" "$SERVICE_URL"
