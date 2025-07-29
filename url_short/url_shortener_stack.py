from aws_cdk import Stack, aws_apigateway as apigw, aws_lambda as _lambda, aws_dynamodb as ddb, RemovalPolicy
from constructs import Construct


class UrlShortenerStack(Stack):

    def __init__(self, scope: Construct, id: str, api: apigw.IRestApi, props, **kwargs):
        super().__init__(scope, id, **kwargs)

        table = ddb.Table(self, "UrlShortenerTable",
                          partition_key=ddb.Attribute(
                              name="shortCode", type=ddb.AttributeType.STRING),
                          removal_policy=RemovalPolicy.DESTROY
                          )

        gen_fn = _lambda.Function(self, "ShortenUrlFunction",
                                  runtime=_lambda.Runtime.PYTHON_3_9,
                                  handler="generate.handler",
                                  code=_lambda.Code.from_asset(
                                      "lambda_fns/url_short"),
                                  environment={
                                      "TABLE_NAME": table.table_name,
                                      "DOMAIN": props["custom_domain_name"]
                                  }
                                  )
        table.grant_write_data(gen_fn)

        redir_fn = _lambda.Function(self, "RedirectFunction",
                                    runtime=_lambda.Runtime.PYTHON_3_9,
                                    handler="redirect.handler",
                                    code=_lambda.Code.from_asset(
                                        "lambda_fns/url_short"),
                                    environment={
                                        "TABLE_NAME": table.table_name}
                                    )
        table.grant_read_data(redir_fn)

        # Attach to existing API Gateway
        shorten_res = api.root.add_resource("shorturl")
        shorten_res.add_method("POST", apigw.LambdaIntegration(gen_fn))

        code_res = api.root.add_resource("{code}")
        code_res.add_method("GET", apigw.LambdaIntegration(redir_fn))
