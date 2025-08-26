#!/bin/bash
# Setup script for AWS CDK Private API Gateway project

set -e

# Print colored output
print_green() {
    echo -e "\e[32m$1\e[0m"
}

print_yellow() {
    echo -e "\e[33m$1\e[0m"
}

print_red() {
    echo -e "\e[31m$1\e[0m"
}

# Check prerequisites
check_prerequisites() {
    print_yellow "Checking prerequisites..."
    
    # Check Python version
    if command -v python3 &>/dev/null; then
        python_version=$(python3 --version | cut -d' ' -f2)
        print_green "✓ Python version: $python_version"
    else
        print_red "✗ Python 3 not found. Please install Python 3.9 or later."
        exit 1
    fi
    
    # Check Node.js version
    if command -v node &>/dev/null; then
        node_version=$(node --version)
        print_green "✓ Node.js version: $node_version"
    else
        print_red "✗ Node.js not found. Please install Node.js 18.x or later."
        exit 1
    fi
    
    # Check AWS CLI
    if command -v aws &>/dev/null; then
        aws_version=$(aws --version | cut -d' ' -f1)
        print_green "✓ AWS CLI installed: $aws_version"
    else
        print_red "✗ AWS CLI not found. Please install AWS CLI."
        exit 1
    fi
    
    # Check AWS CDK
    if command -v cdk &>/dev/null; then
        cdk_version=$(cdk --version)
        print_green "✓ AWS CDK installed: $cdk_version"
    else
        print_yellow "! AWS CDK not found. Will install it."
    fi
}

# Create and activate virtual environment
setup_venv() {
    print_yellow "Setting up Python virtual environment..."
    
    if [ -d ".env" ]; then
        print_yellow "Virtual environment already exists. Activating..."
    else
        python3 -m venv .env
        print_green "✓ Virtual environment created."
    fi
    
    # Activate virtual environment
    source .env/bin/activate
    print_green "✓ Virtual environment activated."
}

# Install dependencies
install_dependencies() {
    print_yellow "Installing Python dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    print_green "✓ Python dependencies installed."
    
    # Install AWS CDK if not already installed
    if ! command -v cdk &>/dev/null; then
        print_yellow "Installing AWS CDK..."
        npm install -g aws-cdk
        print_green "✓ AWS CDK installed."
    fi
    
    # Install development dependencies if requested
    if [ "$1" = "--dev" ]; then
        print_yellow "Installing development dependencies..."
        pip install -r requirements-dev.txt
        npm install -g cfn-lint
        
        # Set up pre-commit hooks
        if command -v pre-commit &>/dev/null; then
            pre-commit install
            print_green "✓ Pre-commit hooks installed."
        else
            print_yellow "! pre-commit not available. Skipping hook installation."
        fi
        
        print_green "✓ Development dependencies installed."
    fi
}

# Check AWS configuration
check_aws_config() {
    print_yellow "Checking AWS configuration..."
    
    if aws sts get-caller-identity &>/dev/null; then
        account_id=$(aws sts get-caller-identity --query Account --output text)
        region=$(aws configure get region)
        print_green "✓ AWS configured for account $account_id in region $region"
        
        # Export environment variables for CDK
        export CDK_DEFAULT_ACCOUNT=$account_id
        export CDK_DEFAULT_REGION=$region
        print_green "✓ CDK environment variables set."
    else
        print_red "✗ AWS CLI not configured correctly. Please run 'aws configure'."
        exit 1
    fi
}

# Main function
main() {
    print_green "=== AWS CDK Private API Gateway Setup ==="
    
    check_prerequisites
    setup_venv
    install_dependencies "$1"
    check_aws_config
    
    print_green "=== Setup Complete ==="
    print_yellow "Next steps:"
    echo "1. Update the cdk.json file with your configuration"
    echo "2. Run 'cdk bootstrap' if you haven't already"
    echo "3. Run 'cdk synth' to generate CloudFormation template"
    echo "4. Run 'cdk deploy' to deploy the stack"
    
    print_yellow "Note: Keep the virtual environment active for CDK commands."
}

# Run main function with arguments
main "$1"