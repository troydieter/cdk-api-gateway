from aws_cdk import Stack, Tags
from aws_cdk.aws_ec2 import Vpc, SubnetConfiguration, SubnetType
from aws_cdk.aws_ssm import StringParameter
from constructs import Construct


class VpcStack(Stack):

    def __init__(self, scope: Construct, id: str, props, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ###
        # Tag everything
        Tags.of(self).add("project", props["namespace"])

        vpc = Vpc(self, 'ApiGWVPC',
                  cidr='192.168.31.0/20',
                  max_azs=2,
                  enable_dns_hostnames=True,
                  enable_dns_support=True,
                  subnet_configuration=[
                      SubnetConfiguration(
                          name='Public-Subnet',
                          subnet_type=SubnetType.PUBLIC,
                          cidr_mask=26
                      ),
                      SubnetConfiguration(
                          name='Private-Subnet',
                          subnet_type=SubnetType.PRIVATE_WITH_EGRESS,
                          cidr_mask=26
                      )
                  ],
                  nat_gateways=1,
                  )
        self.vpc = vpc
        priv_subnets = [subnet.subnet_id for subnet in self.vpc.private_subnets]

        count = 1
        for psub in priv_subnets:
            StringParameter(self, 'private-subnet-' + str(count),
                            string_value=psub,
                            parameter_name='/' + props["namespace"] + '/private-subnet-' + str(count)
                            )
            count += 1
