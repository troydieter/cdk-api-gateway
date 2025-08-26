import setuptools

with open("README.md") as fp:
    long_description = fp.read()

setuptools.setup(
    name="api_gateway_private_fanout",
    version="0.2.0",
    description="AWS CDK Python Private API Gateway with Fan-out Pattern",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="NinjaTech AI",
    package_dir={"": "."},
    packages=setuptools.find_packages(),
    install_requires=[
        "aws-cdk-lib>=2.126.0",
        "constructs>=10.3.0",
        "cdk-watchful>=0.7.0",
        "aws-cdk-aws-apigatewayv2-alpha>=2.126.0-alpha.0",
        "aws-cdk-aws-apigatewayv2-integrations-alpha>=2.126.0-alpha.0",
        "aws-xray-sdk>=2.12.1",
        "aws-lambda-powertools>=2.30.2",
    ],
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Utilities",
        "Typing :: Typed",
    ],
)