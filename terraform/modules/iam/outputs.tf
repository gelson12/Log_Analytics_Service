output "task_execution_role_arn" {
  description = "ARN of the ECS task execution role (used by the ECS agent)."
  value       = aws_iam_role.execution.arn
}

output "task_role_arn" {
  description = "ARN of the ECS task role (used by the running container)."
  value       = aws_iam_role.task.arn
}
