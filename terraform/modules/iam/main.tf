################################################################################
# modules/iam — Task execution role + least-privilege task role
#
# The task role grants ONLY s3:GetObject and s3:ListBucket on ONLY the
# specific buckets listed in var.log_buckets.  s3:* on * is intentionally
# absent.
################################################################################

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ─── Task execution role (used by ECS agent to pull image, push logs) ────────

resource "aws_iam_role" "execution" {
  name               = "${var.name}-${var.environment}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ─── Task role (used by the running container) ────────────────────────────────

resource "aws_iam_role" "task" {
  name               = "${var.name}-${var.environment}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task_s3" {
  # List bucket contents (needed for list_objects_v2 pagination)
  statement {
    sid     = "ListLogBuckets"
    actions = ["s3:ListBucket"]
    resources = [
      for b in var.log_buckets : "arn:aws:s3:::${b}"
    ]
  }

  # Read individual objects
  statement {
    sid     = "GetLogObjects"
    actions = ["s3:GetObject"]
    resources = [
      for b in var.log_buckets : "arn:aws:s3:::${b}/*"
    ]
  }
}

resource "aws_iam_policy" "task_s3" {
  name   = "${var.name}-${var.environment}-task-s3"
  policy = data.aws_iam_policy_document.task_s3.json
}

resource "aws_iam_role_policy_attachment" "task_s3" {
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task_s3.arn
}

# Allow container to write structured logs to CloudWatch
data "aws_iam_policy_document" "task_logs" {
  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/ecs/${var.name}-${var.environment}:*"
    ]
  }
}

resource "aws_iam_policy" "task_logs" {
  name   = "${var.name}-${var.environment}-task-logs"
  policy = data.aws_iam_policy_document.task_logs.json
}

resource "aws_iam_role_policy_attachment" "task_logs" {
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task_logs.arn
}
