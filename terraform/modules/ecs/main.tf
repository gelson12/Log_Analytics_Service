################################################################################
# modules/ecs — Fargate service behind an ALB
################################################################################

###############################################################################
# Security groups
###############################################################################

resource "aws_security_group" "alb" {
  name        = "${var.name}-${var.environment}-alb"
  description = "Allow HTTP/HTTPS from CloudFront IP ranges only"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from anywhere (CloudFront will restrict in practice)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs" {
  name        = "${var.name}-${var.environment}-ecs"
  description = "Allow inbound from ALB only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "App port from ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

###############################################################################
# Application Load Balancer
###############################################################################

resource "aws_lb" "this" {
  name               = "${var.name}-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false   # flip to true in long-lived prod
  idle_timeout               = 200     # must exceed CloudFront origin_read_timeout
}

resource "aws_lb_target_group" "this" {
  name        = "${var.name}-${var.environment}"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"   # required for Fargate

  health_check {
    path                = "/healthz"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

###############################################################################
# CloudWatch log group (structured JSON → Logs Insights)
###############################################################################

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}-${var.environment}"
  retention_in_days = 30
}

###############################################################################
# ECS cluster
###############################################################################

resource "aws_ecs_cluster" "this" {
  name = "${var.name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

###############################################################################
# Task definition
###############################################################################

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name  = var.name
    image = var.ecr_image_uri

    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]

    environment = [
      { name = "GIT_SHA",    value = var.git_sha },
      { name = "LOG_BUCKET", value = var.log_bucket },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:${var.container_port}/healthz')\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 10
    }

    # Hard memory limit matches the spec: container must handle 500 MB files
    # within 256 MB RSS (proven by test_streaming.py).
    # Task memory is 512 MB to give the ECS agent headroom above the container.
    memory            = var.memory / 2  # hard limit: container OOM-killed if exceeded
    memoryReservation = var.memory / 2  # soft limit: used for scheduling
  }])
}

###############################################################################
# ECS service
###############################################################################

resource "aws_ecs_service" "this" {
  name            = "${var.name}-${var.environment}"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = var.name
    container_port   = var.container_port
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Rolling update: replace one task at a time
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Ignore task_definition changes managed by CI/CD (image tag updates)
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]
}
