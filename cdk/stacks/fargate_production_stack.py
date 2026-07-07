"""
AgentCore Debugger CDK Stack — Production Architecture

Replaces the single-EC2 docker-compose setup with:
  - S3 + CloudFront for static React frontend (no nginx container)
  - ECS Fargate for the FastAPI backend (auto-scaling, multi-AZ)
  - DynamoDB for application state (replaces SQLite)
  - ALB restricted to CloudFront only
  - WAF on CloudFront (rate limiting + managed rules)
  - Cognito User Pool for authentication
  - KMS encryption, Secrets Manager, CloudWatch monitoring
"""
from aws_cdk import (
    Stack,
    CfnParameter,
    CfnOutput,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_kms as kms,
    aws_logs as logs,
    aws_sns as sns,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_elasticloadbalancingv2 as elbv2,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_wafv2 as wafv2,
    aws_dynamodb as dynamodb,
    aws_cognito as cognito,
    aws_ecr as ecr,
    custom_resources as cr,
)
from constructs import Construct


class FargateProductionStack(Stack):
    """
    AgentCore Debugger stack.

    Architecture:
      CloudFront → S3 (React static)  +  CloudFront → ALB → Fargate (FastAPI)
      DynamoDB for state  |  Cognito for auth  |  WAF for protection
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ====================================================================
        # PARAMETERS
        # ====================================================================

        alert_email = CfnParameter(
            self, "AlertEmail",
            type="String",
            description="Email for CloudWatch alarms (optional)",
            default="",
        )

        backend_cpu = CfnParameter(
            self, "BackendCPU",
            type="Number",
            description="Fargate task CPU units (256=0.25 vCPU, 512=0.5, 1024=1)",
            default=512,
        )

        backend_memory = CfnParameter(
            self, "BackendMemory",
            type="Number",
            description="Fargate task memory in MiB",
            default=1024,
        )

        backend_desired_count = CfnParameter(
            self, "BackendDesiredCount",
            type="Number",
            description="Number of backend Fargate tasks",
            default=1,
        )

        # ====================================================================
        # VPC — multi-AZ with private subnets for Fargate
        # ====================================================================

        vpc = ec2.Vpc(
            self, "DebuggerVPC",
            max_azs=2,
            nat_gateways=0,  # No NAT needed — Fargate in public subnets with SG lockdown
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24,
                ),
            ],
        )

        # S3 gateway endpoint — free, avoids data transfer charges
        vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)

        # ====================================================================
        # KMS KEY
        # ====================================================================

        kms_key = kms.Key(
            self, "DebuggerKMSKey",
            description="AgentCore Debugger encryption key",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
        kms_key.add_alias(f"alias/{Stack.of(self).stack_name}")

        # Grant CloudWatch Logs
        kms_key.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudWatchLogs",
                principals=[iam.ServicePrincipal(f"logs.{Stack.of(self).region}.amazonaws.com")],
                actions=["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
                         "kms:GenerateDataKey*", "kms:CreateGrant", "kms:DescribeKey"],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn":
                            f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:log-group:*"
                    }
                },
            )
        )

        # ====================================================================
        # COGNITO USER POOL (Auth)
        # ====================================================================

        user_pool = cognito.UserPool(
            self, "DebuggerUserPool",
            user_pool_name=f"{Stack.of(self).stack_name}-users",
            self_sign_up_enabled=False,  # Admin-only user creation
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Create groups for RBAC
        for group_name in ["admin", "operator", "viewer"]:
            cognito.CfnUserPoolGroup(
                self, f"Group{group_name.capitalize()}",
                user_pool_id=user_pool.user_pool_id,
                group_name=group_name,
                description=f"{group_name.capitalize()} role for AgentCore Debugger",
            )

        user_pool_client = user_pool.add_client(
            "DebuggerAppClient",
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                # callback URLs updated after CloudFront domain is known
                callback_urls=["http://localhost:5173/auth/callback"],
                logout_urls=["http://localhost:5173"],
            ),
            generate_secret=False,
        )

        user_pool_domain = user_pool.add_domain(
            "DebuggerCognitoDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"{Stack.of(self).stack_name.lower()}-auth",
            ),
        )

        # ====================================================================
        # DYNAMODB TABLE (replaces SQLite)
        # ====================================================================

        state_table = dynamodb.Table(
            self, "DebuggerStateTable",
            table_name=f"{Stack.of(self).stack_name}-state",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # Scales to zero
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=kms_key,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # ====================================================================
        # CLOUDWATCH LOG GROUP
        # ====================================================================

        log_group = logs.LogGroup(
            self, "BackendLogGroup",
            log_group_name=f"/aws/ecs/{Stack.of(self).stack_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            encryption_key=kms_key,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ====================================================================
        # SNS ALERTS
        # ====================================================================

        alert_topic = sns.Topic(
            self, "AlertTopic",
            display_name=f"{Stack.of(self).stack_name} Alerts",
            master_key=kms_key,
        )

        # ====================================================================
        # SECURITY GROUPS
        # ====================================================================

        cloudfront_prefix_list = ec2.Peer.prefix_list("pl-3b927c52")

        alb_sg = ec2.SecurityGroup(
            self, "ALBSecurityGroup",
            vpc=vpc,
            description="ALB - CloudFront access only",
            allow_all_outbound=False,
            disable_inline_rules=True,
        )
        alb_sg.add_egress_rule(
            ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.all_tcp(), "Outbound to VPC",
        )
        alb_sg.add_ingress_rule(
            cloudfront_prefix_list, ec2.Port.tcp(80), "HTTP from CloudFront only",
        )

        backend_sg = ec2.SecurityGroup(
            self, "BackendSecurityGroup",
            vpc=vpc,
            description="Fargate backend tasks",
            allow_all_outbound=True,
        )
        backend_sg.add_ingress_rule(
            alb_sg, ec2.Port.tcp(8000), "From ALB",
        )

        # ====================================================================
        # ECS CLUSTER + FARGATE BACKEND
        # ====================================================================

        cluster = ecs.Cluster(
            self, "DebuggerCluster",
            vpc=vpc,
            cluster_name=f"{Stack.of(self).stack_name}-cluster",
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # Task execution role (ECR pull, log writing)
        task_execution_role = iam.Role(
            self, "TaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )

        # Task role (what the container can do at runtime)
        task_role = iam.Role(
            self, "BackendTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        # Grant permissions to task role
        kms_key.grant_decrypt(task_role)
        state_table.grant_read_write_data(task_role)

        # Bedrock, CloudWatch Logs read, ECR read, S3 config
        task_role.add_to_policy(iam.PolicyStatement(
            sid="BedrockInvoke",
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                "arn:aws:bedrock:*::foundation-model/*",
                f"arn:aws:bedrock:*:{Stack.of(self).account}:inference-profile/*",
            ],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="CloudWatchLogsRead",
            actions=["logs:DescribeLogGroups", "logs:DescribeLogStreams",
                     "logs:FilterLogEvents", "logs:GetLogEvents"],
            resources=[
                f"arn:aws:logs:*:{Stack.of(self).account}:log-group:*",
            ],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"],
            resources=["*"],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="ECRRead",
            actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
                     "ecr:DescribeImages", "ecr:DescribeRepositories",
                     "ecr:BatchCheckLayerAvailability", "ecr:CreateRepository"],
            resources=[
                f"arn:aws:ecr:*:{Stack.of(self).account}:repository/agentcore-*",
                f"arn:aws:ecr:*:{Stack.of(self).account}:repository/bedrock-agentcore-*",
            ],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="ECRAuth",
            actions=["ecr:GetAuthorizationToken"],
            resources=["*"],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="BedrockAgentCore",
            actions=[
                "bedrock-agentcore:CreateAgentRuntime",
                "bedrock-agentcore:UpdateAgentRuntime",
                "bedrock-agentcore:GetAgentRuntime",
                "bedrock-agentcore:ListAgentRuntimes",
                "bedrock-agentcore:DescribeAgentRuntime",
                "bedrock-agentcore:CreateAgentRuntimeEndpoint",
                "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
                "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
                "bedrock-agentcore:GetAgentRuntimeEndpoint",
                "bedrock-agentcore:ListAgentRuntimeEndpoints",
                "bedrock-agentcore:CreateWorkloadIdentity",
                "bedrock-agentcore:GetWorkloadIdentity",
                "bedrock-agentcore:DeleteWorkloadIdentity",
                "bedrock-agentcore:InvokeAgent",
                "bedrock-agentcore:InvokeAgentRuntime",
            ],
            resources=[f"arn:aws:bedrock-agentcore:*:{Stack.of(self).account}:*"],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="S3Config",
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[
                "arn:aws:s3:::agentcore-agents",
                "arn:aws:s3:::agentcore-agents/*",
                "arn:aws:s3:::*/*bedrock_agentcore.yaml",
            ],
        ))

        # CodeBuild service role for building Docker images
        codebuild_role = iam.Role(
            self, "CodeBuildServiceRole",
            role_name=f"codebuild-agentcore-debugger-{Stack.of(self).region}",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        # ecr:GetAuthorizationToken does not support resource-level permissions
        # (AWS limitation) — must be "*". All other ECR actions are scoped.
        codebuild_role.add_to_policy(iam.PolicyStatement(
            sid="ECRAuthToken",
            actions=["ecr:GetAuthorizationToken"],
            resources=["*"],
        ))
        codebuild_role.add_to_policy(iam.PolicyStatement(
            sid="ECRPushPull",
            actions=[
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:PutImage",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload",
            ],
            resources=[
                f"arn:aws:ecr:*:{Stack.of(self).account}:repository/agentcore-*",
                f"arn:aws:ecr:*:{Stack.of(self).account}:repository/bedrock-agentcore-*",
            ],
        ))
        codebuild_role.add_to_policy(iam.PolicyStatement(
            sid="CodeBuildLogs",
            actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            resources=[
                f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:log-group:/aws/codebuild/*",
            ],
        ))
        codebuild_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:GetBucketLocation"],
            resources=[
                f"arn:aws:s3:::codebuild-{Stack.of(self).account}-*",
                f"arn:aws:s3:::codebuild-{Stack.of(self).account}-*/*",
            ],
        ))

        task_role.add_to_policy(iam.PolicyStatement(
            sid="CodeBuildAccess",
            actions=[
                "codebuild:StartBuild",
                "codebuild:BatchGetBuilds",
                "codebuild:BatchGetProjects",
                "codebuild:CreateProject",
            ],
            # Scoped to the builder projects this app creates/starts
            # (codebuild_service names them "bedrock-agentcore-<agent>-builder").
            resources=[
                f"arn:aws:codebuild:{Stack.of(self).region}:{Stack.of(self).account}:project/bedrock-agentcore-*",
            ],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="S3BuildArtifacts",
            actions=["s3:PutObject", "s3:GetObject", "s3:GetBucketLocation",
                     "s3:CreateBucket", "s3:ListBucket", "s3:HeadBucket"],
            resources=[
                f"arn:aws:s3:::codebuild-{Stack.of(self).account}-*",
                f"arn:aws:s3:::codebuild-{Stack.of(self).account}-*/*",
                # CodeBuild source bucket used by the fix -> deploy flow
                f"arn:aws:s3:::bedrock-agentcore-codebuild-sources-{Stack.of(self).account}-*",
                f"arn:aws:s3:::bedrock-agentcore-codebuild-sources-{Stack.of(self).account}-*/*",
            ],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="IAMPassRoleForCodeBuild",
            actions=["iam:PassRole"],
            resources=[codebuild_role.role_arn],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="CognitoUserManagement",
            actions=[
                "cognito-idp:AdminCreateUser",
                "cognito-idp:AdminDeleteUser",
                "cognito-idp:AdminSetUserPassword",
                "cognito-idp:AdminAddUserToGroup",
                "cognito-idp:AdminRemoveUserFromGroup",
                "cognito-idp:AdminListGroupsForUser",
                "cognito-idp:ListUsers",
            ],
            resources=[user_pool.user_pool_arn],
        ))

        # ====================================================================
        # SAMPLE AGENT EXECUTION ROLE
        # Role assumed by the AgentCore Runtime when running the bundled
        # sample (demo) agent. Lets users try the debugger on a known-buggy
        # agent before pointing it at their real agents.
        # ====================================================================
        sample_agent_role = iam.Role(
            self, "SampleAgentExecutionRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Execution role for the bundled sample/demo agent",
        )
        sample_agent_role.add_to_policy(iam.PolicyStatement(
            sid="BedrockInvoke",
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:*::foundation-model/*",
                f"arn:aws:bedrock:*:{Stack.of(self).account}:*",
            ],
        ))
        sample_agent_role.add_to_policy(iam.PolicyStatement(
            sid="CloudWatchLogs",
            actions=["logs:CreateLogGroup", "logs:CreateLogStream",
                     "logs:PutLogEvents", "logs:DescribeLogStreams"],
            resources=[f"arn:aws:logs:*:{Stack.of(self).account}:*"],
        ))
        sample_agent_role.add_to_policy(iam.PolicyStatement(
            sid="S3DeploymentPackage",
            actions=["s3:GetObject"],
            resources=[
                f"arn:aws:s3:::bedrock-agentcore-code-{Stack.of(self).account}-*/*",
            ],
        ))
        # X-Ray for observability traces
        sample_agent_role.add_to_policy(iam.PolicyStatement(
            sid="XRayTracing",
            actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
            resources=["*"],
        ))

        # Allow the backend task to pass the sample agent role to AgentCore
        task_role.add_to_policy(iam.PolicyStatement(
            sid="PassSampleAgentRole",
            actions=["iam:PassRole"],
            resources=[sample_agent_role.role_arn],
        ))
        # Allow passing AgentCore execution roles when redeploying a fixed
        # agent (update_agent_runtime re-passes the agent's existing role).
        # Scoped to the AgentCore execution role naming patterns.
        task_role.add_to_policy(iam.PolicyStatement(
            sid="PassAgentCoreExecutionRoles",
            actions=["iam:PassRole"],
            resources=[
                f"arn:aws:iam::{Stack.of(self).account}:role/AmazonBedrockAgentCoreSDKRuntime-*",
                f"arn:aws:iam::{Stack.of(self).account}:role/AgentCoreExecutionRole-*",
            ],
            conditions={
                "StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}
            },
        ))
        # Allow the backend to create the S3 deployment bucket if absent
        task_role.add_to_policy(iam.PolicyStatement(
            sid="SampleAgentS3Deploy",
            actions=["s3:CreateBucket", "s3:PutObject", "s3:GetObject", "s3:HeadBucket"],
            resources=[
                f"arn:aws:s3:::bedrock-agentcore-code-{Stack.of(self).account}-*",
                f"arn:aws:s3:::bedrock-agentcore-code-{Stack.of(self).account}-*/*",
            ],
        ))

        # Fargate task definition
        task_def = ecs.FargateTaskDefinition(
            self, "BackendTaskDef",
            cpu=int(backend_cpu.value_as_number),
            memory_limit_mib=int(backend_memory.value_as_number),
            execution_role=task_execution_role,
            task_role=task_role,
        )

        ecr_base = f"{Stack.of(self).account}.dkr.ecr.{Stack.of(self).region}.amazonaws.com"

        backend_container = task_def.add_container(
            "backend",
            image=ecs.ContainerImage.from_registry(
                f"{ecr_base}/agentcore-debugger-backend:acd-latest"
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="backend",
                log_group=log_group,
            ),
            environment={
                "AWS_REGION": Stack.of(self).region,
                "AWS_DEFAULT_REGION": Stack.of(self).region,
                "PYTHONPATH": "/app",
                "AUTH_ENABLED": "true",
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_APP_CLIENT_ID": user_pool_client.user_pool_client_id,
                "COGNITO_REGION": Stack.of(self).region,
                "COGNITO_DOMAIN": user_pool_domain.domain_name,
                "DYNAMODB_TABLE_NAME": state_table.table_name,
                "SAMPLE_AGENT_ROLE_ARN": sample_agent_role.role_arn,
            },
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status==200 else 1)\" || exit 1",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )
        backend_container.add_port_mappings(
            ecs.PortMapping(container_port=8000, protocol=ecs.Protocol.TCP)
        )

        # ====================================================================
        # ALB + FARGATE SERVICE
        # ====================================================================

        alb = elbv2.ApplicationLoadBalancer(
            self, "DebuggerALB",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            drop_invalid_header_fields=True,
            idle_timeout=Duration.seconds(600),
        )

        # ALB access logs
        alb_logs_bucket = s3.Bucket(
            self, "ALBLogsBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30), enabled=True)],
        )
        alb.log_access_logs(alb_logs_bucket)

        # Backend target group
        backend_tg = elbv2.ApplicationTargetGroup(
            self, "BackendTargetGroup",
            vpc=vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            deregistration_delay=Duration.seconds(30),
        )

        listener = alb.add_listener(
            "HTTPListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404, content_type="text/plain", message_body="Not Found",
            ),
        )

        listener.add_action(
            "APIRoute",
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api/*"])],
            action=elbv2.ListenerAction.forward([backend_tg]),
        )

        # Route /auth/* and /health and /docs to backend too
        listener.add_action(
            "AuthRoute",
            priority=20,
            conditions=[elbv2.ListenerCondition.path_patterns(["/auth/*", "/health", "/docs", "/redoc", "/openapi.json"])],
            action=elbv2.ListenerAction.forward([backend_tg]),
        )

        # Fargate service
        fargate_service = ecs.FargateService(
            self, "BackendService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=int(backend_desired_count.value_as_number),
            security_groups=[backend_sg],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            assign_public_ip=True,  # Required in public subnets — SG blocks all except ALB
            health_check_grace_period=Duration.seconds(120),
        )

        fargate_service.attach_to_application_target_group(backend_tg)

        # Auto-scaling
        scaling = fargate_service.auto_scale_task_count(min_capacity=1, max_capacity=6)
        scaling.scale_on_cpu_utilization("CpuScaling", target_utilization_percent=70)
        scaling.scale_on_memory_utilization("MemoryScaling", target_utilization_percent=80)

        # ====================================================================
        # S3 BUCKET FOR FRONTEND (static React build)
        # ====================================================================

        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
        )

        # ====================================================================
        # WAF WEB ACL
        # ====================================================================

        waf_acl = wafv2.CfnWebACL(
            self, "DebuggerWAF",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            scope="CLOUDFRONT",
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name=f"{Stack.of(self).stack_name}-waf",
                sampled_requests_enabled=True,
            ),
            name=f"{Stack.of(self).stack_name}-waf",
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=1,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=2000, aggregate_key_type="IP",
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimitRule",
                        sampled_requests_enabled=True,
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=2,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name="AWSManagedRulesCommonRuleSet",
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesCommonRuleSet",
                        sampled_requests_enabled=True,
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesKnownBadInputsRuleSet",
                    priority=3,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name="AWSManagedRulesKnownBadInputsRuleSet",
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesKnownBadInputsRuleSet",
                        sampled_requests_enabled=True,
                    ),
                ),
            ],
        )

        # ====================================================================
        # CLOUDFRONT DISTRIBUTION
        # ====================================================================

        # Origin Access Identity for S3
        oai = cloudfront.OriginAccessIdentity(
            self, "FrontendOAI",
            comment="OAI for AgentCore Debugger frontend",
        )
        frontend_bucket.grant_read(oai)

        distribution = cloudfront.Distribution(
            self, "DebuggerDistribution",
            comment=f"{Stack.of(self).stack_name} - AgentCore Debugger",
            # Default: serve React from S3
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(frontend_bucket, origin_access_identity=oai),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                # API requests → ALB → Fargate
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        alb.load_balancer_dns_name,
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                        custom_headers={"X-Origin-Verify": Stack.of(self).stack_name},
                        read_timeout=Duration.seconds(120),
                        keepalive_timeout=Duration.seconds(60),
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                ),
                # Auth config endpoint → ALB → Fargate
                "/auth/config": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        alb.load_balancer_dns_name,
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                        custom_headers={"X-Origin-Verify": Stack.of(self).stack_name},
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                ),
                # OAuth token exchange endpoint → ALB → Fargate
                # (note: /auth/callback is a SPA route and intentionally falls
                #  through to the default S3 behavior, not the backend)
                "/auth/token": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        alb.load_balancer_dns_name,
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                        custom_headers={"X-Origin-Verify": Stack.of(self).stack_name},
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                ),
                # Health check → ALB → Fargate
                "/health": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        alb.load_balancer_dns_name,
                        protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                ),
            },
            # SPA: return index.html for 403/404 (React Router handles routing)
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            enabled=True,
            default_root_object="index.html",
            web_acl_id=waf_acl.attr_arn,
        )

        # ====================================================================
        # COGNITO CALLBACK URLS (auto-wired to the CloudFront domain)
        # --------------------------------------------------------------------
        # The CloudFront domain isn't known until the distribution exists, so
        # the app client is created with only localhost URLs (above). This
        # custom resource updates the client with the real CloudFront callback
        # / logout URLs after deploy — no manual post-deploy step needed.
        # All other OAuth settings are re-stated here so the update preserves
        # them (UpdateUserPoolClient replaces the client config).
        # ====================================================================
        cf_origin = f"https://{distribution.distribution_domain_name}"
        cr.AwsCustomResource(
            self, "CognitoCallbackUrls",
            on_update=cr.AwsSdkCall(
                service="CognitoIdentityServiceProvider",
                action="updateUserPoolClient",
                parameters={
                    "UserPoolId": user_pool.user_pool_id,
                    "ClientId": user_pool_client.user_pool_client_id,
                    "CallbackURLs": [
                        f"{cf_origin}/auth/callback",
                        "http://localhost:5173/auth/callback",
                    ],
                    "LogoutURLs": [
                        cf_origin,
                        "http://localhost:5173",
                    ],
                    "AllowedOAuthFlows": ["code"],
                    "AllowedOAuthScopes": ["email", "openid", "profile"],
                    "AllowedOAuthFlowsUserPoolClient": True,
                    "SupportedIdentityProviders": ["COGNITO"],
                    "ExplicitAuthFlows": [
                        "ALLOW_REFRESH_TOKEN_AUTH",
                        "ALLOW_USER_SRP_AUTH",
                    ],
                    "RefreshTokenValidity": 30,
                    "EnableTokenRevocation": True,
                },
                # Re-run whenever the CloudFront domain changes.
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"cognito-callbacks-{distribution.distribution_domain_name}"
                ),
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=[user_pool.user_pool_arn],
            ),
            install_latest_aws_sdk=False,
        )

        # ====================================================================
        # CLOUDWATCH ALARMS
        # ====================================================================

        # Fargate CPU alarm
        cloudwatch.Alarm(
            self, "FargateCPUAlarm",
            metric=fargate_service.metric_cpu_utilization(),
            threshold=80,
            evaluation_periods=2,
            alarm_description="Backend Fargate CPU > 80%",
        ).add_alarm_action(cw_actions.SnsAction(alert_topic))

        # ALB 5xx alarm
        cloudwatch.Alarm(
            self, "ALB5xxAlarm",
            metric=alb.metric_http_code_target(
                code=elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
                period=Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=2,
            alarm_description="ALB 5xx errors > 10 in 5 min",
        ).add_alarm_action(cw_actions.SnsAction(alert_topic))

        # ====================================================================
        # OUTPUTS
        # ====================================================================

        CfnOutput(self, "ApplicationURL",
                  value=f"https://{distribution.distribution_domain_name}",
                  description="Application URL (CloudFront)")

        CfnOutput(self, "CloudFrontDistributionId",
                  value=distribution.distribution_id,
                  description="CloudFront Distribution ID")

        CfnOutput(self, "FrontendBucketName",
                  value=frontend_bucket.bucket_name,
                  description="S3 bucket for React frontend — deploy with: aws s3 sync dist/ s3://<bucket>")

        CfnOutput(self, "ALBDnsName",
                  value=alb.load_balancer_dns_name,
                  description="ALB DNS (internal — restricted to CloudFront)")

        CfnOutput(self, "ECSClusterName",
                  value=cluster.cluster_name,
                  description="ECS Cluster name")

        CfnOutput(self, "DynamoDBTableName",
                  value=state_table.table_name,
                  description="DynamoDB state table")

        CfnOutput(self, "CognitoUserPoolId",
                  value=user_pool.user_pool_id,
                  description="Cognito User Pool ID")

        CfnOutput(self, "CognitoAppClientId",
                  value=user_pool_client.user_pool_client_id,
                  description="Cognito App Client ID")

        CfnOutput(self, "CognitoDomain",
                  value=user_pool_domain.domain_name,
                  description="Cognito domain prefix")

        CfnOutput(self, "LogGroupName",
                  value=log_group.log_group_name,
                  description="CloudWatch Log Group for backend")
