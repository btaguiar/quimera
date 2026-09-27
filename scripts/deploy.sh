#!/usr/bin/env bash
# Deploy da demo pública da Quimera (Fase 3b). Runbook completo: docs/deploy.md.
# Requisitos: gcloud autenticado (login + application-default) e bq (vem no SDK).
# Uso:
#   API_TOKEN=... TURNSTILE_SITE_KEY=... TURNSTILE_SECRET_KEY=... bash scripts/deploy.sh
# Idempotente: re-executar só re-deploya (secrets/SA/bindings não são duplicados).
set -euo pipefail

PROJECT="${PROJECT:-quimera-leads}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-quimera-demo}"
SA_NAME="${SA_NAME:-quimera-demo}"
AR_REPO="${AR_REPO:-quimera}"
LEADS_DATASET="${LEADS_DATASET:-quimera}"
BQ_LOCATION="${BQ_LOCATION:-US}"
VERTEX_LOCATION="${VERTEX_LOCATION:-us-central1}"
DAILY_BYTES_BUDGET="${DAILY_BYTES_BUDGET:-10737418240}"
RATE_LIMIT_MAX="${RATE_LIMIT_MAX:-10}"
BUDGET_USD="${BUDGET_USD:-}"            # ex.: 20 -> cria alertas 50/80/100%
API_TOKEN="${API_TOKEN:-}"              # valor do secret (só na 1ª criação)
TURNSTILE_SECRET_KEY="${TURNSTILE_SECRET_KEY:-}"
TURNSTILE_SITE_KEY="${TURNSTILE_SITE_KEY:-}"
PUBLIC_ACCESS="${PUBLIC_ACCESS:-true}"  # false -> exige IAM invoker (sem acesso anonimo)

ALLOW_FLAG="--allow-unauthenticated"
if [ "$PUBLIC_ACCESS" != "true" ]; then
  ALLOW_FLAG="--no-allow-unauthenticated"
fi

log() { printf '\n==> %s\n' "$*"; }

log "projeto e APIs"
gcloud config set project "$PROJECT"
gcloud services enable run cloudbuild artifactregistry secretmanager

SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/${SERVICE}"

log "artifact registry"
if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker --location="$REGION"
fi

log "secrets (cria só se não existirem)"
if ! gcloud secrets describe quimera-api-token >/dev/null 2>&1; then
  [ -n "$API_TOKEN" ] || { echo "API_TOKEN vazio: passe o valor para criar o secret"; exit 1; }
  printf '%s' "$API_TOKEN" | gcloud secrets create quimera-api-token --data-file=-
fi
if ! gcloud secrets describe quimera-turnstile-secret >/dev/null 2>&1; then
  if [ -n "$TURNSTILE_SECRET_KEY" ]; then
    printf '%s' "$TURNSTILE_SECRET_KEY" | gcloud secrets create quimera-turnstile-secret --data-file=-
  else
    echo "aviso: TURNSTILE_SECRET_KEY vazio — o front fica sem Turnstile até o próximo deploy com a chave"
  fi
fi

log "service account (privilégio mínimo da spec)"
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name="Quimera demo (Cloud Run)"
fi
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/bigquery.jobUser --condition=None >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/aiplatform.user --condition=None >/dev/null
bq add-iam-policy-binding \
  --member="serviceAccount:${SA_EMAIL}" \
  --role=roles/bigquery.dataViewer \
  "${PROJECT}:${LEADS_DATASET}" >/dev/null
gcloud secrets add-iam-policy-binding quimera-api-token \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null
if gcloud secrets describe quimera-turnstile-secret >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding quimera-turnstile-secret \
    --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null
fi

log "build (cloud build)"
TAG="$(date -u +%Y%m%dT%H%M%SZ)"
gcloud builds submit --tag="${IMAGE}:${TAG}" .

log "deploy (cloud run)"
SECRETS="API_TOKEN=quimera-api-token:latest"
if gcloud secrets describe quimera-turnstile-secret >/dev/null 2>&1; then
  SECRETS="${SECRETS},TURNSTILE_SECRET_KEY=quimera-turnstile-secret:latest"
fi
gcloud run deploy "$SERVICE" \
  --image="${IMAGE}:${TAG}" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --min-instances=0 --max-instances=1 --concurrency=4 \
  --cpu=1 --memory=1Gi --timeout=120 \
  "$ALLOW_FLAG" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},BQ_LOCATION=${BQ_LOCATION},VERTEX_LOCATION=${VERTEX_LOCATION},EXTRACT_MODEL=gemini-2.5-flash,EMBED_MODEL=text-embedding-005,MAX_BYTES_BILLED=5368709120,LEADS_DATASET=${LEADS_DATASET},DAILY_BYTES_BUDGET=${DAILY_BYTES_BUDGET},RATE_LIMIT_MAX=${RATE_LIMIT_MAX},RATE_LIMIT_WINDOW_S=3600,CACHE_TTL_S=86400,REQUEST_TIMEOUT_S=60,EVAL_DIR=/app/eval,TURNSTILE_SITE_KEY=${TURNSTILE_SITE_KEY}" \
  --set-secrets="$SECRETS"

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')
log "smoke test: $URL"
CURL_AUTH=()
if [ "$PUBLIC_ACCESS" != "true" ]; then
  echo "acesso privado (IAM invoker): smoke test usa identity token do gcloud"
  CURL_AUTH=(-H "Authorization: Bearer $(gcloud auth print-identity-token)")
fi
curl -fsS "${CURL_AUTH[@]}" "$URL/health"; echo
curl -fsS "${CURL_AUTH[@]}" "$URL/metrics" -o /dev/null -w 'metrics: %{http_code}\n'
curl -fsS "${CURL_AUTH[@]}" "$URL/" | grep -qi '<html' && echo 'front: ok'
curl -fsS "${CURL_AUTH[@]}" "$URL/metrics.html" | grep -qi 'anexo' && echo 'anexo: ok'

if [ -n "$BUDGET_USD" ]; then
  log "alertas de orçamento (50/80/100%)"
  BA=$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' | sed 's#.*/##')
  gcloud beta billing budgets create --billing-account="$BA" \
    --display-name="quimera-demo" --budget-amount="${BUDGET_USD}USD" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0 \
    || echo "sem permissão para criar orçamento por API: crie no console (docs/deploy.md)"
else
  echo "BUDGET_USD vazio: alertas não criados (console: Billing > Orçamentos; 50/80/100%)"
fi

if [ "$PUBLIC_ACCESS" != "true" ]; then
  printf '\nDEMO (privada — precisa de IAM invoker): %s\n' "$URL"
  printf 'Para abrir ao público depois: PUBLIC_ACCESS=true bash scripts/deploy.sh\n'
else
  printf '\nDEMO: %s\nANEXO: %s/metrics.html\n' "$URL" "$URL"
fi
