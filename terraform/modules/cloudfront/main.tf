################################################################################
# modules/cloudfront — CloudFront distribution in front of ALB
################################################################################

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.name}-${var.environment}"
  price_class     = "PriceClass_100" # US + Europe — cheapest tier

  origin {
    domain_name = var.alb_dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only" # ALB listener is HTTP; CloudFront terminates TLS
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # ── Default behaviour: /analyze and everything else ──────────────────────
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      # Must forward query strings — bucket/prefix/threshold reach the origin
      query_string = true
      cookies { forward = "none" }
    }

    # Short TTL: log data changes frequently, /analyze is not static
    min_ttl     = 0
    default_ttl = 10
    max_ttl     = 30
  }

  # ── /healthz — never cache, liveness must always hit the container ────────
  ordered_cache_behavior {
    path_pattern           = "/healthz"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  # ── /readyz — never cache, must verify S3 is reachable live ──────────────
  ordered_cache_behavior {
    path_pattern           = "/readyz"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = true # readyz accepts ?bucket= param
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  # ── /version — cache briefly; git SHA doesn't change mid-deployment ───────
  ordered_cache_behavior {
    path_pattern           = "/version"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 60
    max_ttl     = 60
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  # Using CloudFront's default *.cloudfront.net certificate — no ACM needed
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
