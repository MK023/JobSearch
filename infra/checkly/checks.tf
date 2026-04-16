# =============================================================================
# JobSearch — Checkly API Checks
# 6 checks: Health, Health DB, Health Cache, Batch Status, Cache Health, Landing
# =============================================================================

locals {
  base_url = "https://www.jobsearches.cc"

  default_alert_settings = {
    escalation_type         = "RUN_BASED"
    failed_run_threshold    = 1
    minutes_failing         = 5
    reminders_amount        = 0
    reminders_interval      = 5
  }

  default_retry = {
    type                 = "LINEAR"
    base_backoff_seconds = 60
    max_retries          = 2
    max_duration_seconds = 600
    same_region          = true
  }
}


# --- 1. Health (general) ---
resource "checkly_check" "health" {
  name                   = "JobSearch /Health"
  type                   = "API"
  frequency              = 10
  activated              = true
  muted                  = false
  run_parallel           = false
  locations              = ["eu-central-1", "eu-west-1"]
  degraded_response_time = 1000
  max_response_time      = 2000
  use_global_alert_settings = true

  alert_settings {
    escalation_type = "RUN_BASED"
    run_based_escalation {
      failed_run_threshold = 1
    }
    time_based_escalation {
      minutes_failing_threshold = 5
    }
    reminders {
      amount   = 0
      interval = 5
    }
  }

  request {
    method           = "GET"
    url              = "${local.base_url}/health"
    follow_redirects = true
    body_type        = "NONE"

    assertion {
      source     = "STATUS_CODE"
      comparison = "EQUALS"
      target     = "200"
    }
    assertion {
      source     = "JSON_BODY"
      property   = "$.status"
      comparison = "EQUALS"
      target     = "ok"
    }
  }

  retry_strategy {
    type                 = "LINEAR"
    base_backoff_seconds = 60
    max_retries          = 2
    max_duration_seconds = 600
    same_region          = true
  }
}


# --- 2. Health DB (NeonDB dedicated) ---
resource "checkly_check" "health_db" {
  name                   = "JobSearch /Health DB"
  type                   = "API"
  frequency              = 5
  activated              = true
  muted                  = false
  run_parallel           = true
  locations              = ["eu-central-1"]
  degraded_response_time = 1000
  max_response_time      = 3000
  use_global_alert_settings = true

  alert_settings {
    escalation_type = "RUN_BASED"
    run_based_escalation {
      failed_run_threshold = 1
    }
    time_based_escalation {
      minutes_failing_threshold = 5
    }
    reminders {
      amount   = 0
      interval = 5
    }
  }

  request {
    method           = "GET"
    url              = "${local.base_url}/health/db"
    follow_redirects = true
    body_type        = "NONE"

    assertion {
      source     = "STATUS_CODE"
      comparison = "EQUALS"
      target     = "200"
    }
    assertion {
      source     = "JSON_BODY"
      property   = "$.db"
      comparison = "EQUALS"
      target     = "connected"
    }
  }

  retry_strategy {
    type                 = "LINEAR"
    base_backoff_seconds = 60
    max_retries          = 2
    max_duration_seconds = 600
    same_region          = true
  }
}


# --- 3. Health Cache ---
resource "checkly_check" "health_cache" {
  name                   = "JobSearch /Health Cache"
  type                   = "API"
  frequency              = 15
  activated              = true
  muted                  = false
  run_parallel           = true
  locations              = ["eu-central-1"]
  degraded_response_time = 1000
  max_response_time      = 2000
  use_global_alert_settings = true

  alert_settings {
    escalation_type = "RUN_BASED"
    run_based_escalation {
      failed_run_threshold = 1
    }
    time_based_escalation {
      minutes_failing_threshold = 5
    }
    reminders {
      amount   = 0
      interval = 5
    }
  }

  request {
    method           = "GET"
    url              = "${local.base_url}/health/cache"
    follow_redirects = true
    body_type        = "NONE"

    assertion {
      source     = "STATUS_CODE"
      comparison = "EQUALS"
      target     = "200"
    }
    assertion {
      source     = "JSON_BODY"
      property   = "$.status"
      comparison = "EQUALS"
      target     = "ok"
    }
  }
}


# --- 4. Batch Status (authenticated) ---
resource "checkly_check" "batch_status" {
  name                   = "JobSearch /Batch Status"
  type                   = "API"
  frequency              = 15
  activated              = true
  muted                  = false
  run_parallel           = true
  locations              = ["eu-central-1"]
  degraded_response_time = 1000
  max_response_time      = 3000
  use_global_alert_settings = true

  alert_settings {
    escalation_type = "RUN_BASED"
    run_based_escalation {
      failed_run_threshold = 1
    }
    time_based_escalation {
      minutes_failing_threshold = 5
    }
    reminders {
      amount   = 0
      interval = 5
    }
  }

  request {
    method           = "GET"
    url              = "${local.base_url}/api/v1/batch/status"
    follow_redirects = true
    headers          = { X-API-Key = var.jobsearch_api_key }
    body_type        = "NONE"

    assertion {
      source     = "STATUS_CODE"
      comparison = "EQUALS"
      target     = "200"
    }
  }

  retry_strategy {
    type                 = "LINEAR"
    base_backoff_seconds = 60
    max_retries          = 2
    max_duration_seconds = 600
    same_region          = true
  }
}


# --- 5. Cache Health (legacy — checks cache errors via /health) ---
resource "checkly_check" "cache_health_legacy" {
  name                   = "JobSearch /Cache Errors"
  type                   = "API"
  frequency              = 60
  activated              = true
  muted                  = false
  run_parallel           = true
  locations              = ["eu-central-1"]
  degraded_response_time = 1000
  max_response_time      = 2000
  use_global_alert_settings = true

  alert_settings {
    escalation_type = "RUN_BASED"
    run_based_escalation {
      failed_run_threshold = 1
    }
    time_based_escalation {
      minutes_failing_threshold = 5
    }
    reminders {
      amount   = 0
      interval = 5
    }
  }

  request {
    method           = "GET"
    url              = "${local.base_url}/health/cache"
    follow_redirects = true
    body_type        = "NONE"

    assertion {
      source     = "STATUS_CODE"
      comparison = "EQUALS"
      target     = "200"
    }
  }
}


# --- 6. Landing Page ---
resource "checkly_check" "landing" {
  name                   = "JobSearch /Landing"
  type                   = "API"
  frequency              = 30
  activated              = true
  muted                  = false
  run_parallel           = true
  locations              = ["eu-central-1"]
  degraded_response_time = 2000
  max_response_time      = 5000
  use_global_alert_settings = true

  alert_settings {
    escalation_type = "RUN_BASED"
    run_based_escalation {
      failed_run_threshold = 1
    }
    time_based_escalation {
      minutes_failing_threshold = 5
    }
    reminders {
      amount   = 0
      interval = 5
    }
  }

  request {
    method           = "GET"
    url              = "${local.base_url}/"
    follow_redirects = true
    body_type        = "NONE"

    assertion {
      source     = "STATUS_CODE"
      comparison = "LESS_THAN"
      target     = "400"
    }
  }

  retry_strategy {
    type                 = "LINEAR"
    base_backoff_seconds = 60
    max_retries          = 2
    max_duration_seconds = 600
    same_region          = true
  }
}
