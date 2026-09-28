output "api_url" {
  description = "Public URL of the API."
  value       = "${var.certificate_arn == "" ? "http" : "https"}://${aws_lb.main.dns_name}"
}

output "ecr_api_repository" {
  description = "Push the API image here."
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_worker_repository" {
  description = "Push the worker image here."
  value       = aws_ecr_repository.worker.repository_url
}

output "app_secret_arn" {
  description = "Set the secret value (JSON with API_KEYS, ANTHROPIC_API_KEY, LANGSMITH_API_KEY) here."
  value       = aws_secretsmanager_secret.app.arn
}

output "reports_bucket" {
  description = "S3 bucket for benchmark reports."
  value       = aws_s3_bucket.reports.bucket
}

output "log_group" {
  description = "CloudWatch log group for all tasks."
  value       = aws_cloudwatch_log_group.app.name
}

output "run_ingest_command" {
  description = "Run the index job after each deploy (it exits quickly when the index is current)."
  value = join(" ", [
    "aws ecs run-task",
    "--cluster ${aws_ecs_cluster.main.name}",
    "--task-definition ${aws_ecs_task_definition.ingest.family}",
    "--launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", aws_subnet.private[*].id)}],securityGroups=[${aws_security_group.tasks.id}],assignPublicIp=DISABLED}'",
  ])
}
