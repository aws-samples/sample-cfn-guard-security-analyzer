"""EKS Fargate stack for CloudFormation Security Analyzer."""
import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    aws_ecr as ecr,
    aws_eks as eks,
    aws_iam as iam,
    aws_ec2 as ec2,
)
from aws_cdk.lambda_layer_kubectl_v31 import KubectlV31Layer
from constructs import Construct
from config import EnvironmentConfig


class EksStack(Stack):
    """Stack containing EKS Fargate cluster, ECR repository, IRSA, and Kubernetes manifests."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        analysis_table,
        connection_table,
        reports_bucket,
        state_machine,
        admin_username: str = "",  # IAM username to grant cluster admin access (optional)
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        # 1. ECR repository for the FastAPI container image
        self.ecr_repository = self._create_ecr_repository()

        # 2. EKS Fargate cluster with Fargate profile
        self.cluster = self._create_eks_cluster()

        # 2b. Optionally grant an IAM user cluster admin access for kubectl
        if admin_username:
            admin_user = iam.User.from_user_name(self, "AdminUser", admin_username)
            self.cluster.aws_auth.add_user_mapping(
                admin_user, groups=["system:masters"]
            )

        # 3. Create namespace first — everything else depends on it
        self.app_namespace = self.cluster.add_manifest(
            "AppNamespace",
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "cfn-security"},
            },
        )

        # 4. IRSA: service account with IAM role (depends on namespace)
        self.service_account = self._create_service_account(
            analysis_table=analysis_table,
            connection_table=connection_table,
            reports_bucket=reports_bucket,
            state_machine=state_machine,
        )

        # 5. AWS Load Balancer Controller add-on
        self.lb_helm_chart = self._install_lb_controller()

        # 6. Kubernetes manifests (Deployment, Service, Ingress)
        self._create_k8s_manifests(
            analysis_table=analysis_table,
            connection_table=connection_table,
            reports_bucket=reports_bucket,
            state_machine=state_machine,
        )

    def _create_ecr_repository(self) -> ecr.Repository:
        """Create ECR repository for the FastAPI container image.

        Returns:
            ECR Repository construct
        """
        return ecr.Repository(
            self,
            "FastApiRepository",
            repository_name=f"cfn-security-analyzer-v2-{self.config.environment_name}",
            removal_policy=(
                RemovalPolicy.RETAIN
                if self.config.environment_name == "prod"
                else RemovalPolicy.DESTROY
            ),
            empty_on_delete=self.config.environment_name != "prod",
            image_scan_on_push=True,
        )

    def _create_eks_cluster(self) -> eks.Cluster:
        """Create EKS Fargate cluster with a Fargate profile for the app namespace.

        Returns:
            EKS Cluster construct
        """
        # 2 AZs is sufficient for HA and avoids Elastic IP quota issues (default quota is 5)
        vpc = ec2.Vpc(self, "EksVpc", max_azs=2)

        cluster = eks.Cluster(
            self,
            "EksCluster",
            cluster_name=f"cfn-security-v2-{self.config.environment_name}",
            version=eks.KubernetesVersion.V1_31,
            kubectl_layer=KubectlV31Layer(self, "KubectlLayer"),
            default_capacity=0,  # Fargate only, no managed node group
            vpc=vpc,
        )

        # Tag VPC subnets for AWS Load Balancer Controller discovery.
        # The controller uses these tags to determine which subnets to place ALBs in.
        # Applied at the VPC level to avoid circular dependencies with cluster resources.
        for subnet in cluster.vpc.public_subnets:
            cdk.Tags.of(subnet).add("kubernetes.io/role/elb", "1")
        for subnet in cluster.vpc.private_subnets:
            cdk.Tags.of(subnet).add("kubernetes.io/role/internal-elb", "1")

        # Fargate profile for the application namespace
        cluster.add_fargate_profile(
            "AppFargateProfile",
            fargate_profile_name=f"cfn-security-app-v2-{self.config.environment_name}",
            selectors=[eks.Selector(namespace="cfn-security")],
        )

        # Fargate profile for kube-system (needed for ALB controller, CoreDNS)
        cluster.add_fargate_profile(
            "SystemFargateProfile",
            fargate_profile_name=f"cfn-security-system-v2-{self.config.environment_name}",
            selectors=[eks.Selector(namespace="kube-system")],
        )

        # Patch CoreDNS for Fargate — required for DNS resolution.
        # Uses KubernetesPatch (strategic merge) instead of add_manifest (kubectl apply)
        # to avoid "spec.selector: Required value" errors on partial Deployment specs.
        coredns_patch = eks.KubernetesPatch(
            self,
            "CoreDnsFargatePatch",
            cluster=cluster,
            resource_name="deployment/coredns",
            resource_namespace="kube-system",
            apply_patch={
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "eks.amazonaws.com/compute-type": "fargate",
                            }
                        }
                    }
                }
            },
            restore_patch={
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "eks.amazonaws.com/compute-type": "ec2",
                            }
                        }
                    }
                }
            },
        )

        return cluster

    def _create_service_account(
        self,
        *,
        analysis_table,
        connection_table,
        reports_bucket,
        state_machine,
    ) -> eks.ServiceAccount:
        """Create Kubernetes service account with IRSA for AWS access.

        Grants:
        - DynamoDB read/write on analysis and connection tables
        - S3 read/write on reports bucket
        - Step Functions start execution
        - Bedrock AgentCore invoke

        Returns:
            EKS ServiceAccount construct
        """
        sa = self.cluster.add_service_account(
            "AppServiceAccount",
            name="cfn-security-sa",
            namespace="cfn-security",
        )
        # Ensure namespace exists before creating the SA manifest
        sa.node.add_dependency(self.app_namespace)

        # DynamoDB read/write on both tables
        analysis_table.grant_read_write_data(sa)
        connection_table.grant_read_write_data(sa)

        # S3 read/write on reports bucket
        reports_bucket.grant_read_write(sa)

        # Step Functions start execution
        state_machine.grant_start_execution(sa)

        # Bedrock AgentCore invoke — scoped to this account's runtimes
        sa.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/*",
                ],
            )
        )

        return sa

    def _install_lb_controller(self):
        """Install the AWS Load Balancer Controller as a cluster add-on.
        
        Returns:
            HelmChart construct for dependency ordering
        """
        # Create the service account first via CDK for IRSA
        lb_sa = self.cluster.add_service_account(
            "LbControllerServiceAccount",
            name="aws-load-balancer-controller",
            namespace="kube-system",
        )

        lb_sa.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "elasticloadbalancing:*",
                    "ec2:Describe*",
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:RevokeSecurityGroupIngress",
                    "ec2:CreateSecurityGroup",
                    "ec2:DeleteSecurityGroup",
                    "ec2:CreateTags",
                    "ec2:DeleteTags",
                    "iam:CreateServiceLinkedRole",
                    "cognito-idp:DescribeUserPoolClient",
                    "acm:ListCertificates",
                    "acm:DescribeCertificate",
                    "waf-regional:*",
                    "wafv2:*",
                    "shield:*",
                    "tag:GetResources",
                    "tag:TagResources",
                ],
                resources=["*"],
            )
        )

        # Install Helm chart — tell it NOT to create the SA (CDK already did).
        # wait=True ensures controller pods are healthy before CDK proceeds,
        # which is critical because the controller's ValidatingWebhook must be
        # serving before any Ingress resource can be created.
        chart = self.cluster.add_helm_chart(
            "AwsLoadBalancerController",
            chart="aws-load-balancer-controller",
            repository="https://aws.github.io/eks-charts",
            namespace="kube-system",
            release="aws-load-balancer-controller",
            wait=True,
            values={
                "clusterName": self.cluster.cluster_name,
                "serviceAccount": {
                    "create": False,
                    "name": "aws-load-balancer-controller",
                },
                "region": self.region,
                "vpcId": self.cluster.vpc.vpc_id,
            },
        )
        # Ensure SA exists before Helm tries to use it
        chart.node.add_dependency(lb_sa)
        return chart

    def _create_k8s_manifests(
        self,
        *,
        analysis_table,
        connection_table,
        reports_bucket,
        state_machine,
    ) -> None:
        """Generate Kubernetes Deployment, Service, and Ingress manifests."""
        import hashlib
        import time

        app_label = "cfn-security-analyzer"
        namespace = "cfn-security"
        image_uri = self.ecr_repository.repository_uri_for_tag("latest")
        # Force rolling update on each deploy
        deploy_hash = hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]

        # --- Deployment ---
        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": app_label,
                "namespace": namespace,
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": app_label}},
                "template": {
                    "metadata": {"labels": {"app": app_label}},
                    "spec": {
                        "serviceAccountName": self.service_account.service_account_name,
                        "containers": [
                            {
                                "name": app_label,
                                "image": image_uri,
                                "imagePullPolicy": "Always",
                                "ports": [{"containerPort": 8000}],
                                "resources": {
                                    "requests": {
                                        "cpu": "256m",
                                        "memory": "512Mi",
                                    },
                                    "limits": {
                                        "cpu": "512m",
                                        "memory": "1Gi",
                                    },
                                },
                                "livenessProbe": {
                                    "httpGet": {
                                        "path": "/health",
                                        "port": 8000,
                                    },
                                    "periodSeconds": 30,
                                },
                                "readinessProbe": {
                                    "httpGet": {
                                        "path": "/health",
                                        "port": 8000,
                                    },
                                    "periodSeconds": 10,
                                },
                                "env": [
                                    {
                                        "name": "ANALYSIS_TABLE_NAME",
                                        "value": analysis_table.table_name,
                                    },
                                    {
                                        "name": "CONNECTION_TABLE_NAME",
                                        "value": connection_table.table_name,
                                    },
                                    {
                                        "name": "REPORTS_BUCKET_NAME",
                                        "value": reports_bucket.bucket_name,
                                    },
                                    {
                                        "name": "STATE_MACHINE_ARN",
                                        "value": state_machine.state_machine_arn,
                                    },
                                    {
                                        "name": "DEPLOY_HASH",
                                        "value": deploy_hash,
                                    },
                                    {
                                        "name": "SECURITY_ANALYZER_AGENT_ARN",
                                        "value": os.environ.get("SECURITY_ANALYZER_AGENT_ARN", ""),
                                    },
                                    {
                                        "name": "CRAWLER_AGENT_ARN",
                                        "value": os.environ.get("CRAWLER_AGENT_ARN", ""),
                                    },
                                    {
                                        "name": "PROPERTY_ANALYZER_AGENT_ARN",
                                        "value": os.environ.get("PROPERTY_ANALYZER_AGENT_ARN", ""),
                                    },
                                    {
                                        "name": "GUARD_RULE_AGENT_ARN",
                                        "value": os.environ.get("GUARD_RULE_AGENT_ARN", ""),
                                    },
                                ],
                            }
                        ],
                    },
                },
            },
        }

        deployment = self.cluster.add_manifest("AppDeployment", deployment_manifest)
        deployment.node.add_dependency(self.app_namespace)

        # --- Service (ClusterIP, port 8000) ---
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": app_label,
                "namespace": namespace,
            },
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": app_label},
                "ports": [
                    {
                        "port": 8000,
                        "targetPort": 8000,
                        "protocol": "TCP",
                    }
                ],
            },
        }

        service = self.cluster.add_manifest("AppService", service_manifest)
        service.node.add_dependency(self.app_namespace)

        # --- Ingress (HTTP ALB, internet-facing) ---
        ingress_manifest = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{app_label}-ingress",
                "namespace": namespace,
                "annotations": {
                    "alb.ingress.kubernetes.io/scheme": "internet-facing",
                    "alb.ingress.kubernetes.io/target-type": "ip",
                    "alb.ingress.kubernetes.io/healthcheck-path": "/health",
                },
            },
            "spec": {
                "ingressClassName": "alb",
                "rules": [
                    {
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": app_label,
                                            "port": {"number": 8000},
                                        }
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        }

        ingress = self.cluster.add_manifest("AppIngress", ingress_manifest)
        ingress.node.add_dependency(service)
        ingress.node.add_dependency(self.lb_helm_chart)

        # --- Exports ---
        CfnOutput(
            self,
            "AlbDnsName",
            value=f"kubectl get ingress -n {namespace} -o jsonpath='{{.items[0].status.loadBalancer.ingress[0].hostname}}'",
            description="Run this command to get the ALB DNS after pods are running",
            export_name=f"cfn-security-alb-dns-v2-{self.config.environment_name}",
        )

        CfnOutput(
            self,
            "EcrRepositoryUri",
            value=self.ecr_repository.repository_uri,
            description="ECR repository URI for the FastAPI container image",
            export_name=f"cfn-security-ecr-uri-v2-{self.config.environment_name}",
        )
