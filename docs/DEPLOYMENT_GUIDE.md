# Deployment Guide for Private API Gateway with Fan-out Pattern

This guide provides step-by-step instructions for deploying the Private API Gateway with Fan-out Pattern using AWS CDK.

## Prerequisites

Before you begin, ensure you have the following:

1. **AWS Account**: An active AWS account with appropriate permissions
2. **AWS CLI**: Installed and configured with credentials
3. **Node.js**: Version 18.x or later
4. **Python**: Version 3.9 or later
5. **AWS CDK**: Version 2.x installed globally
6. **Domain Name**: A domain registered in Route53 or delegated to Route53
7. **SSL Certificate**: A wildcard certificate in AWS Certificate Manager

## Step 1: Prepare Your Environment

### Install Required Tools

```bash
# Install AWS CDK globally
npm install -g aws-cdk

# Verify installation
cdk --version
```

### Clone the Repository

```bash
git clone <repository-url>
cd cdk-api-gateway-feature-private_api_gateway
```

### Set Up Python Virtual Environment

```bash
# Create virtual environment
python -m venv .env

# Activate on Linux/macOS
source .env/bin/activate

# Activate on Windows
.env\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt
```

## Step 2: Configure the Deployment

### Update cdk.json

Edit the `cdk.json` file to include your specific configuration:

```json
{
  "app": "python3 app.py",
  "context": {
    "namespace": "your-namespace",
    "hosted_zone_id": "YOUR_HOSTED_ZONE_ID",
    "hosted_zone_name": "yourdomain.com",
    "cert_arn": "arn:aws:acm:region:account:certificate/certificate-id",
    "custom_domain_name": "api.yourdomain.com",
    "alarm_email": "your-email@example.com",
    "vpc_cidr": "10.0.0.0/16",
    "use_improved_stack": "true",
    "environment": "dev",
    "owner": "your-name"
  }
}
```

Replace the following values:
- `namespace`: A unique identifier for your deployment
- `hosted_zone_id`: Your Route53 hosted zone ID
- `hosted_zone_name`: Your domain name
- `cert_arn`: ARN of your wildcard certificate in ACM
- `custom_domain_name`: Subdomain for your API
- `alarm_email`: Email address for CloudWatch alarms
- `vpc_cidr`: CIDR block for the VPC (adjust as needed)
- `environment`: Deployment environment (dev, test, prod)
- `owner`: Your name or team name

### Set Environment Variables

Set the AWS account and region environment variables:

```bash
# Linux/macOS
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=$(aws configure get region)

# Windows PowerShell
$env:CDK_DEFAULT_ACCOUNT = aws sts get-caller-identity --query Account --output text
$env:CDK_DEFAULT_REGION = aws configure get region
```

## Step 3: Deploy the Stack

### Bootstrap CDK (First-time only)

If this is your first time using CDK in this AWS account and region, you need to bootstrap it:

```bash
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION
```

### Synthesize the CloudFormation Template

```bash
cdk synth
```

Review the generated CloudFormation template in the `cdk.out` directory.

### Deploy the Stack

```bash
cdk deploy
```

During deployment, you may be prompted to approve IAM changes. Review them and approve if they match your expectations.

## Step 4: Verify the Deployment

### Check Outputs

After successful deployment, CDK will output important information:
- VPC ID
- API Gateway endpoint URL
- Custom domain URL

### Test the API

Use Postman or curl to test the API:

```bash
# Replace with your actual API endpoint and API key
curl -X POST \
  https://api.yourdomain.com/your-namespace/SendEvent \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: your-api-key' \
  -d '{"message": "hello", "status": "created"}'
```

### Verify Lambda Execution

Check CloudWatch Logs to verify that your Lambda functions are being triggered correctly:

1. Open the AWS Management Console
2. Navigate to CloudWatch > Log Groups
3. Find the log groups for your Lambda functions
4. Verify that messages are being processed

## Step 5: Clean Up (When No Longer Needed)

To avoid incurring charges for resources you no longer need, destroy the stack:

```bash
cdk destroy
```

## Troubleshooting

### Common Issues

1. **Certificate Not Found**: Ensure the certificate ARN is correct and the certificate is in the same region as your deployment.

2. **Domain Name Not Resolving**: DNS propagation can take time. Wait up to 48 hours for DNS changes to propagate globally.

3. **API Gateway 403 Errors**: Check that you're using the correct API key and that your request is properly formatted.

4. **VPC Endpoint Issues**: Ensure your VPC endpoints are correctly configured and that security groups allow the necessary traffic.

5. **Lambda Function Errors**: Check CloudWatch Logs for detailed error messages from your Lambda functions.

### Getting Help

If you encounter issues not covered in this guide:

1. Check the AWS CDK documentation: https://docs.aws.amazon.com/cdk/
2. Review the AWS service-specific documentation
3. Open an issue in the project repository

## Security Considerations

- The API Gateway is deployed as a private endpoint, accessible only from within the VPC
- Consider implementing additional security measures based on your specific requirements
- Regularly review and rotate API keys
- Monitor CloudWatch Logs and Metrics for suspicious activity
- Consider enabling AWS Config and AWS Security Hub for enhanced security monitoring

## Cost Optimization

To optimize costs:

1. Use the appropriate instance types and sizes for your workload
2. Monitor usage and adjust capacity as needed
3. Consider implementing auto-scaling for variable workloads
4. Delete the stack when not in use for development or testing environments
5. Use AWS Cost Explorer to identify cost-saving opportunities