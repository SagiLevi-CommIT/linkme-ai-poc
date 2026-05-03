output "artifacts_bucket_name" {
  description = "Name of the S3 bucket used for CodeBuild build artifacts"
  value       = aws_s3_bucket.artifacts.id
}

output "codebuild_project_names" {
  description = "Map of project key to CodeBuild project name"
  value       = { for k, v in aws_codebuild_project.this : k => v.name }
}

output "codebuild_role_arns" {
  description = "Map of project key to CodeBuild IAM role ARN"
  value       = { for k, v in aws_iam_role.codebuild : k => v.arn }
}
